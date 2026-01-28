"""Handler contexts for MCP handlers."""

from dataclasses import dataclass, field
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.message import CloseSSEStreamCallback
from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParamsMeta

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class HandlerContext(Generic[SessionT, LifespanContextT]):
    """Base context shared by all handlers."""

    session: SessionT
    lifespan_context: LifespanContextT
    # NOTE: This is typed as Any to avoid circular imports. The actual type is
    # mcp.server.experimental.request_context.Experimental, but importing it here
    # triggers mcp.server.__init__ -> mcpserver -> tools -> back to this module.
    # The Server sets this to an Experimental instance at runtime.
    experimental: Any = field(default=None, kw_only=True)


@dataclass
class RequestHandlerContext(HandlerContext[SessionT, LifespanContextT], Generic[SessionT, LifespanContextT, RequestT]):
    """Context for request handlers."""

    request_id: RequestId = field(kw_only=True)
    meta: RequestParamsMeta | None = field(kw_only=True)
    request: RequestT | None = field(default=None, kw_only=True)
    close_sse_stream: CloseSSEStreamCallback | None = field(default=None, kw_only=True)
    close_standalone_sse_stream: CloseSSEStreamCallback | None = field(default=None, kw_only=True)


@dataclass
class NotificationHandlerContext(HandlerContext[SessionT, LifespanContextT]):
    """Context for notification handlers."""
