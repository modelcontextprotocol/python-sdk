from dataclasses import dataclass, field
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams, TaskMetadata

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class Experimental:
    task_metadata: TaskMetadata | None = None

    @property
    def is_task(self) -> bool:
        return self.task_metadata is not None


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    experimental: Experimental = field(default_factory=Experimental)
    request: RequestT | None = None
