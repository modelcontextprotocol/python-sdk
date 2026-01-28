"""Request context for MCP handlers."""

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
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    """Context passed to request and notification handlers.

    For request handlers, all fields are populated.
    For notification handlers, request-specific fields (request_id, meta, etc.) are None.
    """

    session: SessionT
    lifespan_context: LifespanContextT
    # NOTE: This is typed as Any to avoid circular imports. The actual type is
    # mcp.server.experimental.request_context.Experimental, but importing it here
    # triggers mcp.server.__init__ -> mcpserver -> tools -> back to this module.
    # The Server sets this to an Experimental instance at runtime.
    experimental: Any = field(default=None, kw_only=True)
    request_id: RequestId | None = field(default=None, kw_only=True)
    meta: RequestParamsMeta | None = field(default=None, kw_only=True)
    request: RequestT | None = field(default=None, kw_only=True)
    close_sse_stream: CloseSSEStreamCallback | None = field(default=None, kw_only=True)
    close_standalone_sse_stream: CloseSSEStreamCallback | None = field(default=None, kw_only=True)
