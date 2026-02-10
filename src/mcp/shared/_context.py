"""Request context for MCP handlers."""

from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.client import BaseClientSession
from mcp.shared.session import CommonBaseSession
from mcp.types import RequestId, RequestParamsMeta

SessionT = TypeVar("SessionT", bound=CommonBaseSession[Any, Any, Any, Any, Any] | BaseClientSession)

@dataclass(kw_only=True)
class RequestContext(Generic[SessionT]):
    """Common context for handling incoming requests."""

    request_id: RequestId
    meta: RequestParamsMeta | None
    session: SessionT
