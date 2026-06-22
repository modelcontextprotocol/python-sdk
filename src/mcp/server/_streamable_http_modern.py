"""Single-exchange HTTP serving for protocol version 2026-07-28.

Private module — entry is via `StreamableHTTPSessionManager.handle_request`.
The legacy streamable-HTTP transport is untouched and remains the supported
path for earlier protocol revisions.

A 2026-07-28 request is a self-contained POST: no `initialize` handshake, no
`Mcp-Session-Id`, one JSON-RPC request in, one JSON-RPC response out. This
module handles such a request directly in the ASGI task - no memory streams,
no per-request task group, no `JSONRPCDispatcher`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

import anyio
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.connection import Connection
from mcp.server.runner import serve_one
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.inbound import ERROR_CODE_HTTP_STATUS, InboundLadderRejection, classify_inbound_request
from mcp.shared.message import MessageMetadata, ServerMessageMetadata
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    INVALID_REQUEST,
    PARSE_ERROR,
    ClientCapabilities,
    ErrorData,
    Implementation,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)

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
    requests to the client.
    """

    transport: TransportContext
    request_id: RequestId
    message_metadata: MessageMetadata
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)
    can_send_request: bool = field(default=False, init=False)

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        # TODO(D-005a): buffer and stream as SSE once the JSON-vs-SSE response mode lands.
        return None

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        # TODO(D-005a): no progressToken plumbing yet; ships with the SSE response mode.
        return None


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

    # TODO(D-005a): validate Accept once the JSON-vs-SSE response mode is settled.

    if request.method != "POST":
        # HTTP-layer rejection (Allow accompanies 405 per RFC 9110) — happens
        # before JSON-RPC parsing, so it doesn't go through `_write`.
        await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, send)
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
    )
    msg = await serve_one(app, req, connection=connection, dctx=dctx, lifespan_state=lifespan_state)
    await _write(msg, scope, receive, send)
