from dataclasses import dataclass
from typing import Any, Generic, Protocol

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


class CloseSSEStreamCallback(Protocol):  # pragma: no cover
    """Callback to close SSE stream for polling behavior (SEP-1699).

    Args:
        retry_interval: Optional retry interval in ms to send before closing.
                       If None, uses the transport's default retry interval.

    Returns:
        True if the stream was found and closed, False otherwise.
    """

    async def __call__(self, retry_interval: int | None = None) -> bool: ...


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    request: RequestT | None = None
    # Callback to close SSE stream for polling behavior (SEP-1699)
    # None if not on streamable HTTP transport or no event store configured
    close_sse_stream: CloseSSEStreamCallback | None = None
