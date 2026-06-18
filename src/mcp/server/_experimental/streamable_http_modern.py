"""Experimental, unstable. Single-exchange HTTP serving for protocol version 2026-07-28.

No public API; everything in this module may change or vanish without
deprecation. The legacy streamable-HTTP transport is untouched and remains the
supported entry point.

A 2026-07-28 request is a self-contained POST: no `initialize` handshake, no
`Mcp-Session-Id`, one JSON-RPC request in, one JSON-RPC response out. This
module handles such a request directly in the ASGI task - no memory streams,
no per-request task group, no `JSONRPCDispatcher`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import anyio
import anyio.abc
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.runner import ServerRunner, otel_middleware
from mcp.server.transport_security import TransportSecurityMiddleware
from mcp.shared.dispatcher import CallOptions, OnNotify, OnRequest
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.message import MessageMetadata, ServerMessageMetadata
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    PARSE_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)

if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

logger = logging.getLogger(__name__)

MODERN_PROTOCOL_VERSION: Final[str] = "2026-07-28"
"""The protocol version this module serves. Kept local so it does not leak into
`SUPPORTED_PROTOCOL_VERSIONS` or the legacy handshake."""


@dataclass
class _SingleExchangeDispatchContext:
    """`DispatchContext` for one inbound HTTP request.

    Structurally satisfies `mcp.shared.dispatcher.DispatchContext`. The
    back-channel is closed by construction: a 2026-07-28 server cannot send
    requests to the client.
    """

    transport: TransportContext
    request_id: RequestId
    message_metadata: MessageMetadata
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)
    can_send_request: bool = False

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        return None

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        # TODO: no progressToken plumbing yet.
        return None


class SingleExchangeDispatcher:
    """Dispatcher for exactly one inbound JSON-RPC request over a single HTTP POST.

    The exception->wire boundary lives here (mirrors `JSONRPCDispatcher`'s
    role). Implements the `Dispatcher` Protocol so `ServerRunner` /
    `Connection` / `ServerSession` accept it; `run()` is never driven.
    """

    def __init__(self, request: Request) -> None:
        self._request = request
        self._tctx = TransportContext(
            kind="streamable-http",
            can_send_request=False,
            headers=request.headers,
        )

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
        *,
        _related_request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        _related_request_id: RequestId | None = None,
    ) -> None:
        # TODO: buffer and stream as SSE once the response-mode design lands.
        return None

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        raise RuntimeError("SingleExchangeDispatcher.run() is never driven; use handle()")

    async def handle(self, req: JSONRPCRequest, on_request: OnRequest) -> JSONRPCResponse | JSONRPCError:
        """Dispatch one request and map any exception to a `JSONRPCError`."""
        dctx = _SingleExchangeDispatchContext(
            transport=self._tctx,
            request_id=req.id,
            message_metadata=ServerMessageMetadata(request_context=self._request),
        )
        try:
            result = await on_request(dctx, req.method, req.params)
            return JSONRPCResponse(jsonrpc="2.0", id=req.id, result=result)
        except MCPError as e:
            return JSONRPCError(jsonrpc="2.0", id=req.id, error=e.error)
        except ValidationError:
            return JSONRPCError(
                jsonrpc="2.0",
                id=req.id,
                error=ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data=""),
            )
        # TODO: consolidate the three exception->ErrorData copies once the
        # code=0 compat pin in JSONRPCDispatcher is lifted.
        except Exception:
            logger.exception("handler for %r raised", req.method)
            return JSONRPCError(
                jsonrpc="2.0",
                id=req.id,
                error=ErrorData(code=INTERNAL_ERROR, message="Internal server error"),
            )


async def handle_modern_request(
    manager: StreamableHTTPSessionManager,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    """ASGI handler for a single 2026-07-28 POST.

    Called from `StreamableHTTPSessionManager.handle_request` when the
    `MCP-Protocol-Version` header is `2026-07-28`. Never sets `Mcp-Session-Id`.
    """
    request = Request(scope, receive)

    security = TransportSecurityMiddleware(manager.security_settings)
    err = await security.validate_request(request, is_post=(request.method == "POST"))
    if err is not None:
        await err(scope, receive, send)
        return

    # TODO: validate Accept header once the JSON-vs-SSE response-mode design is settled.

    if request.method != "POST":
        # TODO: GET/DELETE rejection (405 + -32601) lands with the validation ladder.
        await Response(status_code=405)(scope, receive, send)
        return

    body = await request.body()
    try:
        req = JSONRPCRequest.model_validate_json(body)
    except ValidationError:
        msg = JSONRPCError(jsonrpc="2.0", id=None, error=ErrorData(code=PARSE_ERROR, message="Parse error"))
        await Response(
            msg.model_dump_json(by_alias=True, exclude_none=True),
            status_code=400,
            media_type="application/json",
        )(scope, receive, send)
        return

    dispatcher = SingleExchangeDispatcher(request)
    # TODO: per-request lifespan re-entry matches stateless_http=True today; revisit in #2893.
    async with manager.app.lifespan(manager.app) as lifespan_state:
        runner = ServerRunner(
            server=manager.app,
            dispatcher=dispatcher,
            lifespan_state=lifespan_state,
            has_standalone_channel=False,
            stateless=True,
            dispatch_middleware=[otel_middleware],
        )
        runner.connection.protocol_version = MODERN_PROTOCOL_VERSION
        try:
            msg = await dispatcher.handle(req, runner._compose_on_request())  # type: ignore[reportPrivateUsage]
        finally:
            await runner.connection.exit_stack.aclose()

    # TODO: error.code -> HTTP status mapping is a follow-up; 200 for all JSONRPCError bodies for now.
    await Response(
        msg.model_dump_json(by_alias=True, exclude_none=True),
        status_code=200,
        media_type="application/json",
    )(scope, receive, send)
