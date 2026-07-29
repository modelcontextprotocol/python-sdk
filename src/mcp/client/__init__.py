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
from mcp.client.client import Client
from mcp.client.context import ClientRequestContext
from mcp.client.extension import (
    ClaimContext,
    ClientExtension,
    NotificationBinding,
    ResultClaim,
    UnexpectedClaimedResult,
    advertise,
)
from mcp.client.session import ClientSession, IncomingMessage
from mcp.shared._lazy_submodules import submodule_getattr as _submodule_getattr

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
    "IncomingMessage",
    "InMemoryResponseCacheStore",
    "InputRequiredRoundsExceededError",
    "NotificationBinding",
    "ResponseCacheStore",
    "ResultClaim",
    "Transport",
    "UnexpectedClaimedResult",
    "advertise",
]

# `mcp.client.<submodule>` (stdio, sse, session_group, auth, ...) resolves by
# attribute access even before that submodule was imported: the lazy `mcp`
# package no longer imports them all up front. See mcp.shared._lazy_submodules.
__getattr__ = _submodule_getattr(__name__)
