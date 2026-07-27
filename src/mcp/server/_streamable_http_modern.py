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
from typing import TYPE_CHECKING, Any, Final, cast

import anyio
from anyio.streams.memory import MemoryObjectSendStream
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    HEADER_MISMATCH,
    INVALID_REQUEST,
    PARSE_ERROR,
    PROTOCOL_VERSION_META_KEY,
    ErrorData,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ProgressToken,
    RequestId,
)
from mcp_types import methods as _methods
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.connection import Connection
from mcp.server.runner import modern_error_data, serve_one
from mcp.server.streamable_http import check_accept_headers
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.inbound import (
    ERROR_CODE_HTTP_STATUS,
    MCP_PARAM_HEADER_PREFIX,
    InboundLadderRejection,
    InboundModernRoute,
    classify_inbound_request,
    find_duplicated_routing_header,
    validate_mcp_param_headers,
)
from mcp.shared.jsonrpc_dispatcher import progress_token_from_params
from mcp.shared.message import MessageMetadata, ServerMessageMetadata
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)


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


async def _to_jsonrpc_response(
    request_id: RequestId, coro: Awaitable[dict[str, Any]]
) -> JSONRPCResponse | JSONRPCError:
    """Await ``coro`` and wrap its outcome as the JSON-RPC reply for ``request_id``.

    The exception-to-wire boundary for the modern HTTP entry, composed around
    `serve_one`: `modern_error_data` maps the shared ladder and surfaces
    anything else as a generic `INTERNAL_ERROR` so handler internals never
    reach the wire.
    """
    try:
        result = await coro
    except Exception as exc:
        return JSONRPCError(jsonrpc="2.0", id=request_id, error=modern_error_data(exc))
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


async def _write_rejection(
    rejection: InboundLadderRejection,
    request_id: RequestId,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """Send a ladder rejection as its JSON-RPC error with the table-mapped HTTP status."""
    rej = JSONRPCError(
        jsonrpc="2.0",
        id=request_id,
        error=ErrorData(code=rejection.code, message=rejection.message, data=rejection.data),
    )
    await _write(rej, scope, receive, send)


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


_MCP_PARAM_PREFIX_LOWER: Final = MCP_PARAM_HEADER_PREFIX.lower()

_MCP_PARAM_LIST_PAGE_CAP: Final = 100
"""Page cap for the schema-resolving tools/list walk: a buggy paginator degrades to a logged skip, not a hang."""


async def _tool_input_schema(
    app: Server[Any],
    request: Request,
    request_id: RequestId,
    verdict: InboundModernRoute,
    lifespan_state: Any,
    name: str,
) -> Any | None:
    """Resolve `name`'s inputSchema from the server's own registered `tools/list` handler.

    The listing runs through the normal `serve_one` path, so a visibility-scoped
    catalog yields exactly what *this* caller was advertised. Returns None
    (caller skips validation) when the listing fails or never advertises the tool.
    """
    meta = {
        PROTOCOL_VERSION_META_KEY: verdict.protocol_version,
        CLIENT_CAPABILITIES_META_KEY: verdict.client_capabilities,
    }
    if verdict.client_info is not None:
        # Optional key: a conforming pair-only caller omits it rather than sending null.
        meta[CLIENT_INFO_META_KEY] = verdict.client_info
    list_params: dict[str, Any] = {"_meta": meta}
    try:
        _methods.validate_client_request("tools/list", verdict.protocol_version, list_params)
    except ValidationError:
        # Client-fault envelope: the real dispatch produces the INVALID_PARAMS
        # reply, and anything above a debug line would let clients flood the log.
        logger.debug("Mcp-Param header validation skipped: the request envelope fails tools/list validation")
        return None
    seen_cursors: set[str] = set()
    dctx = _SingleExchangeDispatchContext(
        transport=TransportContext(kind="streamable-http", can_send_request=False, headers=request.headers),
        request_id=request_id,
        message_metadata=ServerMessageMetadata(request_context=request),
    )
    for _ in range(_MCP_PARAM_LIST_PAGE_CAP):
        # Fresh Connection per page: serve_one tears down the connection's exit stack on the way out.
        connection = Connection.from_envelope(
            verdict.protocol_version, verdict.client_info, verdict.client_capabilities
        )
        try:
            result = await serve_one(
                app, dctx, "tools/list", list_params, connection=connection, lifespan_state=lifespan_state
            )
            for tool in result.get("tools", []):
                if tool.get("name") == name:
                    return tool.get("inputSchema")
            cursor = result.get("nextCursor")
        except Exception:
            # Fail-open boundary by design: header validation must never break a
            # working call path. Loud, precisely because the skip is fail-open.
            logger.exception("Mcp-Param header validation skipped: the tools/list listing failed")
            return None
        if not isinstance(cursor, str):
            # Listing exhausted without advertising `name`; dispatch owns rejecting an unknown tool.
            return None
        if cursor in seen_cursors:
            logger.warning("Mcp-Param header validation skipped: the tools/list handler returned a cursor cycle")
            return None
        seen_cursors.add(cursor)
        list_params = {"_meta": meta, "cursor": cursor}
    logger.warning(
        "Mcp-Param header validation skipped: tools/list pagination did not terminate within %d pages",
        _MCP_PARAM_LIST_PAGE_CAP,
    )
    return None


async def _mcp_param_rejection(
    app: Server[Any],
    request: Request,
    req: JSONRPCRequest,
    verdict: InboundModernRoute,
    lifespan_state: Any,
) -> InboundLadderRejection | None:
    """Validate a `tools/call` request's `Mcp-Param-*` headers against the called tool's schema.

    Runs pre-dispatch, before any SSE machinery, so a rejection is always a
    plain `application/json` 400 (the spec's MUST). With no `tools/list` handler
    the catalog is undiscoverable and there is no recognized header to validate.
    """
    if req.method != "tools/call" or app.get_request_handler("tools/list") is None:
        return None
    params = req.params or {}
    name = params.get("name")
    if not isinstance(name, str):
        return None
    raw_arguments = params.get("arguments")
    if raw_arguments is not None and not isinstance(raw_arguments, Mapping):
        return None
    arguments: Mapping[str, Any] = cast("Mapping[str, Any]", raw_arguments) if raw_arguments is not None else {}
    # ASGI guarantees lowercase header names, so no case-folding here.
    if not arguments and not any(header.startswith(_MCP_PARAM_PREFIX_LOWER) for header in request.headers):
        # No argument values and no `Mcp-Param-*` headers: no declaration can be violated either way.
        return None
    input_schema = await _tool_input_schema(app, request, req.id, verdict, lifespan_state, name)
    if input_schema is None:
        return None
    return validate_mcp_param_headers(input_schema, arguments, request.headers)


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
    except (ValueError, RecursionError):
        # Not just JSONDecodeError: oversized integer literals raise bare ValueError, deep nesting RecursionError.
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

    if req.method == "subscriptions/listen" and not has_sse:
        # A listen response IS a notification stream, never JSON (the
        # json_response carve-out below), so this one method requires the
        # SSE accept even in JSON-response mode; SSE mode gated it above.
        await Response(status_code=406)(scope, receive, send)
        return

    duplicated = find_duplicated_routing_header(request.headers.items())
    if duplicated is not None:
        # The raw carrier is the only place duplicates are visible; the classifier sees a folded mapping.
        rejection = InboundLadderRejection(code=HEADER_MISMATCH, message=f"{duplicated} header appears more than once")
        await _write_rejection(rejection, req.id, scope, receive, send)
        return

    verdict = classify_inbound_request(decoded, headers=dict(request.headers))
    if isinstance(verdict, InboundLadderRejection):
        await _write_rejection(verdict, req.id, scope, receive, send)
        return

    mcp_param_rejection = await _mcp_param_rejection(app, request, req, verdict, lifespan_state)
    if mcp_param_rejection is not None:
        await _write_rejection(mcp_param_rejection, req.id, scope, receive, send)
        return

    connection = Connection.from_envelope(
        verdict.protocol_version,
        verdict.client_info,
        verdict.client_capabilities,
    )
    dctx = _SingleExchangeDispatchContext(
        transport=TransportContext(kind="streamable-http", can_send_request=False, headers=request.headers),
        request_id=req.id,
        message_metadata=ServerMessageMetadata(request_context=request),
        progress_token=progress_token_from_params(req.params),
    )

    if json_response and req.method != "subscriptions/listen":
        # A listen response IS a notification stream, so it always takes the
        # SSE path below regardless of the JSON-response preference (the
        # TypeScript and Go SDKs route it the same way).
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
