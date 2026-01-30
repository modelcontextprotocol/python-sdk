"""Request context for MCP handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic

from typing_extensions import TypeVar

from mcp.shared.message import CloseSSEStreamCallback
from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParamsMeta

if TYPE_CHECKING:
    from mcp.server.experimental.request_context import Experimental

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass(kw_only=True)
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    """Context passed to request and notification handlers.

    For request handlers, all fields are populated.
    For notification handlers, request-specific fields (request_id, meta, etc.) are None.
    """

    session: SessionT
    lifespan_context: LifespanContextT
    experimental: Experimental | None = None
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None
