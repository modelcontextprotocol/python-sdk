"""Request context for MCP handlers."""

from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import CommonBaseSession
from mcp.types import RequestId, RequestParamsMeta

SessionT_co = TypeVar("SessionT_co", bound=CommonBaseSession[Any, Any, Any, Any, Any], covariant=True)


@dataclass(kw_only=True)
class RequestContext(Generic[SessionT_co]):
    """Common context for handling incoming requests."""

    request_id: RequestId
    meta: RequestParamsMeta | None
    session: SessionT_co
