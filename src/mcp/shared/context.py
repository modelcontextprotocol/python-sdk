from dataclasses import dataclass, field
from typing import Generic, TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams

SessionT = TypeVar("SessionT", bound=BaseSession)
LifespanContextT = TypeVar("LifespanContextT")


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT]):
    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    headers: dict[str, str] = field(default_factory=dict)
