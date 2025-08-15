from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    """Context object containing information about the current MCP request.

    This context is available during request processing and provides access
    to the request metadata, session, and any lifespan-scoped resources.

    Attributes:
        request_id: Unique identifier for the current request
        meta: Optional metadata from the request including progress token
        session: The MCP session handling this request
        lifespan_context: Application-specific context from lifespan initialization
        request: The original request object, if available
    """

    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    request: RequestT | None = None
