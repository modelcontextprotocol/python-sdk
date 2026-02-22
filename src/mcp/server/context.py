from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.server.experimental.request_context import Experimental
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.message import CloseSSEStreamCallback

ServerLifespanContextT = TypeVar("ServerLifespanContextT", default=dict[str, Any])
SessionLifespanContextT = TypeVar("SessionLifespanContextT", default=dict[str, Any])
RequestT = TypeVar("RequestT", default=Any)


@dataclass(kw_only=True)
class ServerRequestContext(
    RequestContext[ServerSession], Generic[ServerLifespanContextT, SessionLifespanContextT, RequestT]
):
    """Context passed to request handlers.

    Attributes:
        server_lifespan_context: Context from server lifespan (runs once at server startup).
            Contains server-level resources like database pools, ML models, shared caches.
        session_lifespan_context: Context from session lifespan (runs per-client connection).
            Contains client-specific resources like user data, auth context.
        experimental: Experimental features context
        request: Optional request-specific data (e.g., auth info from middleware)
        close_sse_stream: Callback to close SSE stream
        close_standalone_sse_stream: Callback to close standalone SSE stream
    """

    server_lifespan_context: ServerLifespanContextT
    session_lifespan_context: SessionLifespanContextT
    experimental: Experimental
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None
