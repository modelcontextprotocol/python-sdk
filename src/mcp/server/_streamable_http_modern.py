"""Single-exchange HTTP serving for protocol version 2026-07-28.

Private module — entry is via `StreamableHTTPSessionManager.handle_request`.
The legacy streamable-HTTP transport is untouched and remains the supported
path for earlier protocol revisions.

A 2026-07-28 request is a self-contained POST: no `initialize` handshake, no
`Mcp-Session-Id`, one JSON-RPC request in, one JSON-RPC response out. JSON
mode handles the request directly in the ASGI task. SSE mode runs the handler
as a sibling task and defers committing to `text/event-stream` until the
handler emits a notification or `_SSE_PING_INTERVAL` elapses, whichever
comes first: a handler that completes (or raises) within that window without
emitting still gets a JSON response with the table-mapped HTTP status, so
the spec's `404`/`400` MUSTs hold for kernel-dispatch errors; a handler that
runs silent past the window commits SSE so the keepalive ping can keep the
connection open behind a proxy idle-read timeout.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, TypeVar

import anyio
from anyio.streams.memory import MemoryObjectSendStream
from mcp_types import (
    INVALID_REQUEST,
    PARSE_ERROR,
    ClientCapabilities,
    ErrorData,
    Implementation,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ProgressToken,
    RequestId,
)
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.connection import Connection
from mcp.server.runner import serve_one
from mcp.server.streamable_http import check_accept_headers
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.inbound import (
    ERROR_CODE_HTTP_STATUS,
    InboundLadderRejection,
    classify_inbound_request,
)
from mcp.shared.jsonrpc_dispatcher import handler_exception_to_error_data, progress_token_from_params
from mcp.shared.message import MessageMetadata, ServerMessageMetadata
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_OK_STATUS = 200


@dataclass
class _SingleExchangeDispatchContext:
    """`DispatchContext` for one inbound HTTP request.

    Structurally satisfies `mcp.shared.dispatcher.DispatchContext`. The
    back-channel is closed by construction: a 2026-07-28 server cannot send
    requests to the client. The SSE sink, when present, carries request-scoped
    notifications onto this request's response stream.
    """

    transport: TransportContext
    request_id: RequestId
    message_metadata: MessageMetadata
    progress_token: ProgressToken | None = None
    sink: MemoryObjectSendStream[bytes] | None = None
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)
    can_send_request: bool = field(default=False, init=False)

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        if self.sink is None:
            return
        body = dict(params) if params is not None else None
        try:
            await self.sink.send(_sse_event(JSONRPCNotification(jsonrpc="2.0", method=method, params=body)))
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            logger.debug("dropped %s: response stream closed", method)

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        if self.progress_token is None:
            return
        params: dict[str, Any] = {"progressToken": self.progress_token, "progress": progress}
        if total is not None:
            params["total"] = total
        if message is not None:
            params["message"] = message
        await self.notify("notifications/progress", params)


def _typed(model: type[_ModelT], raw: Any) -> _ModelT | None:
    """Validate the classifier's raw envelope value into a typed model.

    Rung 1 guarantees the envelope key was present; a ``null`` or mis-shaped
    value falls through to ``ValidationError`` and is treated as not supplied
    so the request still routes.
    """
    try:
        return model.model_validate(raw, by_name=False)
    except ValidationError:
        return None


async def _to_jsonrpc_response(
    request_id: RequestId, coro: Awaitable[dict[str, Any]]
) -> JSONRPCResponse | JSONRPCError:
    """Await ``coro`` and wrap its outcome as the JSON-RPC reply for ``request_id``.

    The exception-to-wire boundary for the modern HTTP entry, composed around
    `serve_one`; the shared `handler_exception_to_error_data` ladder owns the
    mapping.
    """
    try:
        result = await coro
    except Exception as exc:
        error, unexpected = handler_exception_to_error_data(exc)
        if unexpected:
            logger.exception("request handler raised")
        return JSONRPCError(jsonrpc="2.0", id=request_id, error=error)
    return JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result)


_SSE_PING_INTERVAL: float = 15.0
"""Seconds between SSE comment-line keepalives once `text/event-stream` has committed."""

_SSE_HEADERS: Final[list[tuple[bytes, bytes]]] = [
    (b"content-type", b"text/event-stream"),
    (b"cache-control", b"no-cache, no-transform"),
    (b"connection", b"keep-alive"),
    (b"x-accel-buffering", b"no"),
]


def _sse_event(msg: JSONRPCResponse | JSONRPCError | JSONRPCNotification) -> bytes:
    """Serialise a JSON-RPC message as one SSE `event: message` frame.

    SSE mode begins after the handler has emitted, so a `JSONRPCError` here
    always carries the request's id; the `id: null` case lives in `_write`.
    """
    body = msg.model_dump(mode="json", by_alias=True, exclude_none=True)
    data = json.dumps(body, separators=(",", ":"))
    return f"event: message\r\ndata: {data}\r\n\r\n".encode()


async def _write(
    msg: JSONRPCResponse | JSONRPCError,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """Serialise a JSON-RPC reply with the table-mapped HTTP status."""
    status = ERROR_CODE_HTTP_STATUS.get(msg.error.code, _OK_STATUS) if isinstance(msg, JSONRPCError) else _OK_STATUS
    body = msg.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(msg, JSONRPCError) and msg.id is None:
        # JSON-RPC requires `id: null` to appear on the wire when the request
        # id couldn't be parsed; `exclude_none` would otherwise drop it.
        body["id"] = None
    await Response(
        json.dumps(body, separators=(",", ":")),
        status_code=status,
        media_type="application/json",
    )(scope, receive, send)


async def handle_modern_request(
    app: Server[Any],
    security_settings: TransportSecuritySettings | None,
    json_response: bool,
    lifespan_state: Any,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """ASGI handler for a single stateless-era POST.

    Called from `StreamableHTTPSessionManager.handle_request` when the
    `MCP-Protocol-Version` header names a modern revision; the manager enters
    `app.lifespan` once at startup and passes the state in. Never sets
    `Mcp-Session-Id`.
    """
    request = Request(scope, receive)

    security = TransportSecurityMiddleware(security_settings)
    err = await security.validate_request(request, is_post=(request.method == "POST"))
    if err is not None:
        await err(scope, receive, send)
        return

    if request.method != "POST":
        # HTTP-layer rejection (Allow accompanies 405 per RFC 9110) — happens
        # before JSON-RPC parsing, so it doesn't go through `_write`.
        await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, send)
        return

    has_json, has_sse = check_accept_headers(request)
    if not has_json or (not json_response and not has_sse):
        await Response(status_code=406)(scope, receive, send)
        return

    body = await request.body()
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        rej = JSONRPCError(jsonrpc="2.0", id=None, error=ErrorData(code=PARSE_ERROR, message="Parse error"))
        await _write(rej, scope, receive, send)
        return
    try:
        req = JSONRPCRequest.model_validate(decoded)
    except ValidationError:
        # Well-formed JSON that isn't a single request object. The transport
        # spec permits notification POSTs and gives the server two responses
        # (202 accept / 4xx cannot-accept; streamable-http §Sending Messages
        # item 5). The core protocol defines no client→server notifications
        # over HTTP at 2026-07-28 (cancellation is SSE-stream close), so this
        # entry takes the cannot-accept branch. TODO(L57): S4 owns the
        # strict-vs-lenient choice.
        rej = JSONRPCError(
            jsonrpc="2.0",
            id=None,
            error=ErrorData(code=INVALID_REQUEST, message="Body must be a single JSON-RPC request object"),
        )
        await _write(rej, scope, receive, send)
        return

    verdict = classify_inbound_request(decoded, headers=dict(request.headers))
    if isinstance(verdict, InboundLadderRejection):
        rej = JSONRPCError(
            jsonrpc="2.0", id=req.id, error=ErrorData(code=verdict.code, message=verdict.message, data=verdict.data)
        )
        await _write(rej, scope, receive, send)
        return

    connection = Connection.from_envelope(
        verdict.protocol_version,
        _typed(Implementation, verdict.client_info),
        _typed(ClientCapabilities, verdict.client_capabilities),
    )
    dctx = _SingleExchangeDispatchContext(
        transport=TransportContext(kind="streamable-http", can_send_request=False, headers=request.headers),
        request_id=req.id,
        message_metadata=ServerMessageMetadata(request_context=request),
        progress_token=progress_token_from_params(req.params),
    )

    if json_response:
        msg = await _to_jsonrpc_response(
            req.id, serve_one(app, dctx, req.method, req.params, connection=connection, lifespan_state=lifespan_state)
        )
        await _write(msg, scope, receive, send)
        return

    send_ch, recv_ch = anyio.create_memory_object_stream[bytes](0)
    dctx.sink = send_ch
    result: list[JSONRPCResponse | JSONRPCError] = []

    async def run_handler() -> None:
        async with send_ch:
            result.append(
                await _to_jsonrpc_response(
                    req.id,
                    serve_one(app, dctx, req.method, req.params, connection=connection, lifespan_state=lifespan_state),
                )
            )

    async def watch_disconnect(cancel_scope: anyio.CancelScope) -> None:
        while (await receive()).get("type") != "http.disconnect":
            pass  # pragma: no cover
        cancel_scope.cancel()

    async with recv_ch, anyio.create_task_group() as tg:
        tg.start_soon(run_handler)
        tg.start_soon(watch_disconnect, tg.cancel_scope)

        event: bytes | None = None
        done = False
        with anyio.move_on_after(_SSE_PING_INTERVAL):
            try:
                event = await recv_ch.receive()
            except anyio.EndOfStream:
                done = True

        if done:
            # Handler completed within the deferral window without emitting:
            # `application/json` with the table-mapped status. Kernel-dispatch
            # errors (METHOD_NOT_FOUND, missing-capability, INVALID_PARAMS)
            # resolve here in practice.
            await _write(result[0], scope, receive, send)
        else:
            # First notification arrived, or the deferral window elapsed: commit
            # `text/event-stream` and start pinging so a proxy idle-read timeout
            # cannot close the stream (which on this path cancels the handler).
            await send({"type": "http.response.start", "status": _OK_STATUS, "headers": _SSE_HEADERS})
            while not done:
                await send({"type": "http.response.body", "body": event or b": ping\r\n\r\n", "more_body": True})
                event = None
                with anyio.move_on_after(_SSE_PING_INTERVAL):
                    try:
                        event = await recv_ch.receive()
                    except anyio.EndOfStream:
                        done = True
            await send({"type": "http.response.body", "body": _sse_event(result[0]), "more_body": False})

        tg.cancel_scope.cancel()
