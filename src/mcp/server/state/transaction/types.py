from __future__ import annotations
from typing import Awaitable, Callable, Optional, Tuple, TypeAlias, Union

from starlette.requests import Request
from mcp.server.fastmcp import Context
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.session import ServerSession

from mcp.types import TransactionMessagePayload

# Short Context alias (no dependency back to state-machine internals)
FastMCPContext = Context[ServerSession, LifespanResultT, Request]

# Kind + Key used across registry/execution (needs proper typing)
TxKey = Tuple[str, str, str]  # (state, kind, name)

# A registered provider can be a fixed payload or a callable that builds one (optionally context-aware).
TransactionPayloadProvider: TypeAlias = Union[
    TransactionMessagePayload,
    Callable[[Optional[FastMCPContext]], Awaitable[TransactionMessagePayload] | TransactionMessagePayload],
]
