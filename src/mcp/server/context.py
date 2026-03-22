from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.server.experimental.request_context import Experimental
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.message import CloseSSEStreamCallback

LifespanContextT = TypeVar("LifespanContextT", default=dict[str, Any])
RequestT = TypeVar("RequestT", default=Any)


@dataclass(kw_only=True)
class ServerRequestContext(RequestContext[ServerSession], Generic[LifespanContextT, RequestT]):
    lifespan_context: LifespanContextT
    experimental: Experimental
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None
