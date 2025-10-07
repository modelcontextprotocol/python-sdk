from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class SerializableRequestContext:
    """Serializable subset of RequestContext for persistent storage."""

    request_id: RequestId
    operation_token: str | None
    meta: RequestParams.Meta | None
    supports_async: bool


@dataclass
class RequestContext(SerializableRequestContext, Generic[SessionT, LifespanContextT, RequestT]):
    session: SessionT
    lifespan_context: LifespanContextT
    request: RequestT | None = None

    def to_serializable(self) -> SerializableRequestContext:
        """Extract serializable parts of this context."""
        return SerializableRequestContext(
            request_id=self.request_id,
            operation_token=self.operation_token,
            meta=self.meta,
            supports_async=self.supports_async,
        )
