"""Request context for MCP handlers."""

from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParamsMeta

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])


@dataclass(kw_only=True)
class RequestContext(Generic[SessionT]):
    """Common context for handling incoming requests."""

    request_id: RequestId
    meta: RequestParamsMeta | None
    session: SessionT
