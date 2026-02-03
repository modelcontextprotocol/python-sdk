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
    """

    session: SessionT
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
