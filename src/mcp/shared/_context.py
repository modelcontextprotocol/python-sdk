"""Request context for MCP handlers."""

from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParamsMeta

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])


@dataclass(kw_only=True)
class RequestContext(Generic[SessionT]):
    """Common context for handling incoming requests.

    For request handlers, request_id is always populated.
    For notification handlers, request_id is None.

    The tenant_id field is used in multi-tenant server deployments to identify
    which tenant the request belongs to. It is populated from session context
    and enables tenant-specific request handling and isolation.
    """

    session: SessionT
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
    tenant_id: str | None = None
