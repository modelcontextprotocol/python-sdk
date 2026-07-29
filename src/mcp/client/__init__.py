"""MCP Client module."""

from typing import TYPE_CHECKING

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
from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

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
# package no longer imports them all up front (see mcp.shared._lazy). Runtime
# only, so a type checker still flags a misspelled `mcp.client.<name>`.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals())
