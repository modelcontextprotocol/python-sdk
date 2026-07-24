"""MCP Client module."""

from mcp.client._input_required import InputRequiredRoundsExceededError
from mcp.client._transport import Transport
from mcp.client.caching import (
    CacheConfig,
    CacheEntry,
    CacheKey,
    CacheMode,
    InMemoryResponseCacheStore,
    ResponseCacheStore,
)
from mcp.client.client import Client, CursorCycleError, PaginationExceededError
from mcp.client.context import ClientRequestContext
from mcp.client.extension import (
    ClaimContext,
    ClientExtension,
    NotificationBinding,
    ResultClaim,
    UnexpectedClaimedResult,
    advertise,
)
from mcp.client.session import ClientSession

__all__ = [
    "CacheConfig",
    "CacheEntry",
    "CacheKey",
    "CacheMode",
    "ClaimContext",
    "Client",
    "ClientExtension",
    "ClientRequestContext",
    "ClientSession",
    "CursorCycleError",
    "InMemoryResponseCacheStore",
    "InputRequiredRoundsExceededError",
    "NotificationBinding",
    "PaginationExceededError",
    "ResponseCacheStore",
    "ResultClaim",
    "Transport",
    "UnexpectedClaimedResult",
    "advertise",
]
