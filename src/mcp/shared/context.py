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
    # TODO: Multi-tenancy - RequestContext lacks tenant_id field. Need to add tenant_id to track
    # which tenant this request belongs to. All handlers should use this tenant_id to scope their
    # operations and prevent cross-tenant data access.
    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    request: RequestT | None = None
