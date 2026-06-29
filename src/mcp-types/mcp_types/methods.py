"""Per-version method maps and parse/serialize functions for MCP traffic.

This module is supported public API; the `mcp_types.v*` packages it draws on
are internal validators and not for direct import.

Surface maps key `(method, version)` to per-version wire types (key absence is
the version gate; shape validation is per schema era, i.e. 2025-11-25 for every
pre-2026 version and 2026-07-28 for 2026). Monolith maps key `method` to the
version-free `mcp_types` models user code receives."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from types import MappingProxyType, UnionType
from typing import Any, Final, Literal, TypeVar, get_args

from pydantic import BaseModel, TypeAdapter

import mcp_types as types
import mcp_types.v2025_11_25 as v2025
import mcp_types.v2026_07_28 as v2026
from mcp_types.version import KNOWN_PROTOCOL_VERSIONS

__all__ = [
    "CACHEABLE_METHODS",
    "CLIENT_NOTIFICATIONS",
    "CLIENT_REQUESTS",
    "CLIENT_RESULTS",
    "CacheableMethod",
    "MONOLITH_NOTIFICATIONS",
    "MONOLITH_REQUESTS",
    "MONOLITH_RESULTS",
    "SERVER_NOTIFICATIONS",
    "SERVER_REQUESTS",
    "SERVER_RESULTS",
    "SPEC_CLIENT_METHODS",
    "SPEC_CLIENT_NOTIFICATION_METHODS",
    "parse_client_notification",
    "parse_client_request",
    "parse_client_result",
    "parse_server_notification",
    "parse_server_request",
    "parse_server_result",
    "serialize_server_result",
    "validate_client_notification",
    "validate_client_request",
    "validate_client_result",
    "validate_server_result",
]


# --- Surface maps: client-to-server ---

CLIENT_REQUESTS: Final[Mapping[tuple[str, str], type[BaseModel]]] = MappingProxyType(
    {
        # 2024-11-05
        ("completion/complete", "2024-11-05"): v2025.CompleteRequest,
        ("initialize", "2024-11-05"): v2025.InitializeRequest,
        ("logging/setLevel", "2024-11-05"): v2025.SetLevelRequest,
        ("ping", "2024-11-05"): v2025.PingRequest,
        ("prompts/get", "2024-11-05"): v2025.GetPromptRequest,
        ("prompts/list", "2024-11-05"): v2025.ListPromptsRequest,
        ("resources/list", "2024-11-05"): v2025.ListResourcesRequest,
        ("resources/read", "2024-11-05"): v2025.ReadResourceRequest,
        ("resources/subscribe", "2024-11-05"): v2025.SubscribeRequest,
        ("resources/templates/list", "2024-11-05"): v2025.ListResourceTemplatesRequest,
        ("resources/unsubscribe", "2024-11-05"): v2025.UnsubscribeRequest,
        ("tools/call", "2024-11-05"): v2025.CallToolRequest,
        ("tools/list", "2024-11-05"): v2025.ListToolsRequest,
        # 2025-03-26
        ("completion/complete", "2025-03-26"): v2025.CompleteRequest,
        ("initialize", "2025-03-26"): v2025.InitializeRequest,
        ("logging/setLevel", "2025-03-26"): v2025.SetLevelRequest,
        ("ping", "2025-03-26"): v2025.PingRequest,
        ("prompts/get", "2025-03-26"): v2025.GetPromptRequest,
        ("prompts/list", "2025-03-26"): v2025.ListPromptsRequest,
        ("resources/list", "2025-03-26"): v2025.ListResourcesRequest,
        ("resources/read", "2025-03-26"): v2025.ReadResourceRequest,
        ("resources/subscribe", "2025-03-26"): v2025.SubscribeRequest,
        ("resources/templates/list", "2025-03-26"): v2025.ListResourceTemplatesRequest,
        ("resources/unsubscribe", "2025-03-26"): v2025.UnsubscribeRequest,
        ("tools/call", "2025-03-26"): v2025.CallToolRequest,
        ("tools/list", "2025-03-26"): v2025.ListToolsRequest,
        # 2025-06-18
        ("completion/complete", "2025-06-18"): v2025.CompleteRequest,
        ("initialize", "2025-06-18"): v2025.InitializeRequest,
        ("logging/setLevel", "2025-06-18"): v2025.SetLevelRequest,
        ("ping", "2025-06-18"): v2025.PingRequest,
        ("prompts/get", "2025-06-18"): v2025.GetPromptRequest,
        ("prompts/list", "2025-06-18"): v2025.ListPromptsRequest,
        ("resources/list", "2025-06-18"): v2025.ListResourcesRequest,
        ("resources/read", "2025-06-18"): v2025.ReadResourceRequest,
        ("resources/subscribe", "2025-06-18"): v2025.SubscribeRequest,
        ("resources/templates/list", "2025-06-18"): v2025.ListResourceTemplatesRequest,
        ("resources/unsubscribe", "2025-06-18"): v2025.UnsubscribeRequest,
        ("tools/call", "2025-06-18"): v2025.CallToolRequest,
        ("tools/list", "2025-06-18"): v2025.ListToolsRequest,
        # 2025-11-25 (tasks/* deliberately absent)
        ("completion/complete", "2025-11-25"): v2025.CompleteRequest,
        ("initialize", "2025-11-25"): v2025.InitializeRequest,
        ("logging/setLevel", "2025-11-25"): v2025.SetLevelRequest,
        ("ping", "2025-11-25"): v2025.PingRequest,
        ("prompts/get", "2025-11-25"): v2025.GetPromptRequest,
        ("prompts/list", "2025-11-25"): v2025.ListPromptsRequest,
        ("resources/list", "2025-11-25"): v2025.ListResourcesRequest,
        ("resources/read", "2025-11-25"): v2025.ReadResourceRequest,
        ("resources/subscribe", "2025-11-25"): v2025.SubscribeRequest,
        ("resources/templates/list", "2025-11-25"): v2025.ListResourceTemplatesRequest,
        ("resources/unsubscribe", "2025-11-25"): v2025.UnsubscribeRequest,
        ("tools/call", "2025-11-25"): v2025.CallToolRequest,
        ("tools/list", "2025-11-25"): v2025.ListToolsRequest,
        # 2026-07-28 (lifecycle, logging, subscribe pair removed; discover/listen added)
        ("completion/complete", "2026-07-28"): v2026.CompleteRequest,
        ("prompts/get", "2026-07-28"): v2026.GetPromptRequest,
        ("prompts/list", "2026-07-28"): v2026.ListPromptsRequest,
        ("resources/list", "2026-07-28"): v2026.ListResourcesRequest,
        ("resources/read", "2026-07-28"): v2026.ReadResourceRequest,
        ("resources/templates/list", "2026-07-28"): v2026.ListResourceTemplatesRequest,
        ("server/discover", "2026-07-28"): v2026.DiscoverRequest,
        ("subscriptions/listen", "2026-07-28"): v2026.SubscriptionsListenRequest,
        ("tools/call", "2026-07-28"): v2026.CallToolRequest,
        ("tools/list", "2026-07-28"): v2026.ListToolsRequest,
    }
)

CLIENT_NOTIFICATIONS: Final[Mapping[tuple[str, str], type[BaseModel]]] = MappingProxyType(
    {
        # 2024-11-05
        ("notifications/cancelled", "2024-11-05"): v2025.CancelledNotification,
        ("notifications/initialized", "2024-11-05"): v2025.InitializedNotification,
        ("notifications/progress", "2024-11-05"): v2025.ProgressNotification,
        ("notifications/roots/list_changed", "2024-11-05"): v2025.RootsListChangedNotification,
        # 2025-03-26
        ("notifications/cancelled", "2025-03-26"): v2025.CancelledNotification,
        ("notifications/initialized", "2025-03-26"): v2025.InitializedNotification,
        ("notifications/progress", "2025-03-26"): v2025.ProgressNotification,
        ("notifications/roots/list_changed", "2025-03-26"): v2025.RootsListChangedNotification,
        # 2025-06-18
        ("notifications/cancelled", "2025-06-18"): v2025.CancelledNotification,
        ("notifications/initialized", "2025-06-18"): v2025.InitializedNotification,
        ("notifications/progress", "2025-06-18"): v2025.ProgressNotification,
        ("notifications/roots/list_changed", "2025-06-18"): v2025.RootsListChangedNotification,
        # 2025-11-25 (tasks/status deliberately absent)
        ("notifications/cancelled", "2025-11-25"): v2025.CancelledNotification,
        ("notifications/initialized", "2025-11-25"): v2025.InitializedNotification,
        ("notifications/progress", "2025-11-25"): v2025.ProgressNotification,
        ("notifications/roots/list_changed", "2025-11-25"): v2025.RootsListChangedNotification,
        # 2026-07-28 (initialized, progress and roots/list_changed removed)
        ("notifications/cancelled", "2026-07-28"): v2026.CancelledNotification,
    }
)


# --- Surface maps: server-to-client ---

SERVER_REQUESTS: Final[Mapping[tuple[str, str], type[BaseModel]]] = MappingProxyType(
    {
        # 2024-11-05
        ("ping", "2024-11-05"): v2025.PingRequest,
        ("roots/list", "2024-11-05"): v2025.ListRootsRequest,
        ("sampling/createMessage", "2024-11-05"): v2025.CreateMessageRequest,
        # 2025-03-26
        ("ping", "2025-03-26"): v2025.PingRequest,
        ("roots/list", "2025-03-26"): v2025.ListRootsRequest,
        ("sampling/createMessage", "2025-03-26"): v2025.CreateMessageRequest,
        # 2025-06-18 (adds elicitation/create)
        ("elicitation/create", "2025-06-18"): v2025.ElicitRequest,
        ("ping", "2025-06-18"): v2025.PingRequest,
        ("roots/list", "2025-06-18"): v2025.ListRootsRequest,
        ("sampling/createMessage", "2025-06-18"): v2025.CreateMessageRequest,
        # 2025-11-25 (tasks/* deliberately absent)
        ("elicitation/create", "2025-11-25"): v2025.ElicitRequest,
        ("ping", "2025-11-25"): v2025.PingRequest,
        ("roots/list", "2025-11-25"): v2025.ListRootsRequest,
        ("sampling/createMessage", "2025-11-25"): v2025.CreateMessageRequest,
        # 2026-07-28: none (schema defines no ServerRequest union)
    }
)

SERVER_NOTIFICATIONS: Final[Mapping[tuple[str, str], type[BaseModel]]] = MappingProxyType(
    {
        # 2024-11-05
        ("notifications/cancelled", "2024-11-05"): v2025.CancelledNotification,
        ("notifications/message", "2024-11-05"): v2025.LoggingMessageNotification,
        ("notifications/progress", "2024-11-05"): v2025.ProgressNotification,
        ("notifications/prompts/list_changed", "2024-11-05"): v2025.PromptListChangedNotification,
        ("notifications/resources/list_changed", "2024-11-05"): v2025.ResourceListChangedNotification,
        ("notifications/resources/updated", "2024-11-05"): v2025.ResourceUpdatedNotification,
        ("notifications/tools/list_changed", "2024-11-05"): v2025.ToolListChangedNotification,
        # 2025-03-26
        ("notifications/cancelled", "2025-03-26"): v2025.CancelledNotification,
        ("notifications/message", "2025-03-26"): v2025.LoggingMessageNotification,
        ("notifications/progress", "2025-03-26"): v2025.ProgressNotification,
        ("notifications/prompts/list_changed", "2025-03-26"): v2025.PromptListChangedNotification,
        ("notifications/resources/list_changed", "2025-03-26"): v2025.ResourceListChangedNotification,
        ("notifications/resources/updated", "2025-03-26"): v2025.ResourceUpdatedNotification,
        ("notifications/tools/list_changed", "2025-03-26"): v2025.ToolListChangedNotification,
        # 2025-06-18
        ("notifications/cancelled", "2025-06-18"): v2025.CancelledNotification,
        ("notifications/message", "2025-06-18"): v2025.LoggingMessageNotification,
        ("notifications/progress", "2025-06-18"): v2025.ProgressNotification,
        ("notifications/prompts/list_changed", "2025-06-18"): v2025.PromptListChangedNotification,
        ("notifications/resources/list_changed", "2025-06-18"): v2025.ResourceListChangedNotification,
        ("notifications/resources/updated", "2025-06-18"): v2025.ResourceUpdatedNotification,
        ("notifications/tools/list_changed", "2025-06-18"): v2025.ToolListChangedNotification,
        # 2025-11-25 (adds elicitation/complete; tasks/status deliberately absent)
        ("notifications/cancelled", "2025-11-25"): v2025.CancelledNotification,
        ("notifications/elicitation/complete", "2025-11-25"): v2025.ElicitationCompleteNotification,
        ("notifications/message", "2025-11-25"): v2025.LoggingMessageNotification,
        ("notifications/progress", "2025-11-25"): v2025.ProgressNotification,
        ("notifications/prompts/list_changed", "2025-11-25"): v2025.PromptListChangedNotification,
        ("notifications/resources/list_changed", "2025-11-25"): v2025.ResourceListChangedNotification,
        ("notifications/resources/updated", "2025-11-25"): v2025.ResourceUpdatedNotification,
        ("notifications/tools/list_changed", "2025-11-25"): v2025.ToolListChangedNotification,
        # 2026-07-28 (adds subscriptions/acknowledged; elicitation/complete removed)
        ("notifications/cancelled", "2026-07-28"): v2026.CancelledNotification,
        ("notifications/message", "2026-07-28"): v2026.LoggingMessageNotification,
        ("notifications/progress", "2026-07-28"): v2026.ProgressNotification,
        ("notifications/prompts/list_changed", "2026-07-28"): v2026.PromptListChangedNotification,
        ("notifications/resources/list_changed", "2026-07-28"): v2026.ResourceListChangedNotification,
        ("notifications/resources/updated", "2026-07-28"): v2026.ResourceUpdatedNotification,
        ("notifications/subscriptions/acknowledged", "2026-07-28"): v2026.SubscriptionsAcknowledgedNotification,
        ("notifications/tools/list_changed", "2026-07-28"): v2026.ToolListChangedNotification,
    }
)


# --- Surface maps: results ---

SERVER_RESULTS: Final[Mapping[tuple[str, str], type[BaseModel] | UnionType]] = MappingProxyType(
    {
        # 2024-11-05
        ("completion/complete", "2024-11-05"): v2025.CompleteResult,
        ("initialize", "2024-11-05"): v2025.InitializeResult,
        ("logging/setLevel", "2024-11-05"): v2025.EmptyResult,
        ("ping", "2024-11-05"): v2025.EmptyResult,
        ("prompts/get", "2024-11-05"): v2025.GetPromptResult,
        ("prompts/list", "2024-11-05"): v2025.ListPromptsResult,
        ("resources/list", "2024-11-05"): v2025.ListResourcesResult,
        ("resources/read", "2024-11-05"): v2025.ReadResourceResult,
        ("resources/subscribe", "2024-11-05"): v2025.EmptyResult,
        ("resources/templates/list", "2024-11-05"): v2025.ListResourceTemplatesResult,
        ("resources/unsubscribe", "2024-11-05"): v2025.EmptyResult,
        ("tools/call", "2024-11-05"): v2025.CallToolResult,
        ("tools/list", "2024-11-05"): v2025.ListToolsResult,
        # 2025-03-26
        ("completion/complete", "2025-03-26"): v2025.CompleteResult,
        ("initialize", "2025-03-26"): v2025.InitializeResult,
        ("logging/setLevel", "2025-03-26"): v2025.EmptyResult,
        ("ping", "2025-03-26"): v2025.EmptyResult,
        ("prompts/get", "2025-03-26"): v2025.GetPromptResult,
        ("prompts/list", "2025-03-26"): v2025.ListPromptsResult,
        ("resources/list", "2025-03-26"): v2025.ListResourcesResult,
        ("resources/read", "2025-03-26"): v2025.ReadResourceResult,
        ("resources/subscribe", "2025-03-26"): v2025.EmptyResult,
        ("resources/templates/list", "2025-03-26"): v2025.ListResourceTemplatesResult,
        ("resources/unsubscribe", "2025-03-26"): v2025.EmptyResult,
        ("tools/call", "2025-03-26"): v2025.CallToolResult,
        ("tools/list", "2025-03-26"): v2025.ListToolsResult,
        # 2025-06-18
        ("completion/complete", "2025-06-18"): v2025.CompleteResult,
        ("initialize", "2025-06-18"): v2025.InitializeResult,
        ("logging/setLevel", "2025-06-18"): v2025.EmptyResult,
        ("ping", "2025-06-18"): v2025.EmptyResult,
        ("prompts/get", "2025-06-18"): v2025.GetPromptResult,
        ("prompts/list", "2025-06-18"): v2025.ListPromptsResult,
        ("resources/list", "2025-06-18"): v2025.ListResourcesResult,
        ("resources/read", "2025-06-18"): v2025.ReadResourceResult,
        ("resources/subscribe", "2025-06-18"): v2025.EmptyResult,
        ("resources/templates/list", "2025-06-18"): v2025.ListResourceTemplatesResult,
        ("resources/unsubscribe", "2025-06-18"): v2025.EmptyResult,
        ("tools/call", "2025-06-18"): v2025.CallToolResult,
        ("tools/list", "2025-06-18"): v2025.ListToolsResult,
        # 2025-11-25
        ("completion/complete", "2025-11-25"): v2025.CompleteResult,
        ("initialize", "2025-11-25"): v2025.InitializeResult,
        ("logging/setLevel", "2025-11-25"): v2025.EmptyResult,
        ("ping", "2025-11-25"): v2025.EmptyResult,
        ("prompts/get", "2025-11-25"): v2025.GetPromptResult,
        ("prompts/list", "2025-11-25"): v2025.ListPromptsResult,
        ("resources/list", "2025-11-25"): v2025.ListResourcesResult,
        ("resources/read", "2025-11-25"): v2025.ReadResourceResult,
        ("resources/subscribe", "2025-11-25"): v2025.EmptyResult,
        ("resources/templates/list", "2025-11-25"): v2025.ListResourceTemplatesResult,
        ("resources/unsubscribe", "2025-11-25"): v2025.EmptyResult,
        ("tools/call", "2025-11-25"): v2025.CallToolResult,
        ("tools/list", "2025-11-25"): v2025.ListToolsResult,
        # 2026-07-28 (dual-result rows use the version's union aliases)
        ("completion/complete", "2026-07-28"): v2026.CompleteResult,
        ("prompts/get", "2026-07-28"): v2026.AnyGetPromptResult,
        ("prompts/list", "2026-07-28"): v2026.ListPromptsResult,
        ("resources/list", "2026-07-28"): v2026.ListResourcesResult,
        ("resources/read", "2026-07-28"): v2026.AnyReadResourceResult,
        ("resources/templates/list", "2026-07-28"): v2026.ListResourceTemplatesResult,
        ("server/discover", "2026-07-28"): v2026.DiscoverResult,
        ("subscriptions/listen", "2026-07-28"): v2026.SubscriptionsListenResult,
        ("tools/call", "2026-07-28"): v2026.AnyCallToolResult,
        ("tools/list", "2026-07-28"): v2026.ListToolsResult,
    }
)
"""Results servers send, keyed by the originating client request's (method, version)."""

CLIENT_RESULTS: Final[Mapping[tuple[str, str], type[BaseModel] | UnionType]] = MappingProxyType(
    {
        # 2024-11-05
        ("ping", "2024-11-05"): v2025.EmptyResult,
        ("roots/list", "2024-11-05"): v2025.ListRootsResult,
        ("sampling/createMessage", "2024-11-05"): v2025.CreateMessageResult,
        # 2025-03-26
        ("ping", "2025-03-26"): v2025.EmptyResult,
        ("roots/list", "2025-03-26"): v2025.ListRootsResult,
        ("sampling/createMessage", "2025-03-26"): v2025.CreateMessageResult,
        # 2025-06-18
        ("elicitation/create", "2025-06-18"): v2025.ElicitResult,
        ("ping", "2025-06-18"): v2025.EmptyResult,
        ("roots/list", "2025-06-18"): v2025.ListRootsResult,
        ("sampling/createMessage", "2025-06-18"): v2025.CreateMessageResult,
        # 2025-11-25
        ("elicitation/create", "2025-11-25"): v2025.ElicitResult,
        ("ping", "2025-11-25"): v2025.EmptyResult,
        ("roots/list", "2025-11-25"): v2025.ListRootsResult,
        ("sampling/createMessage", "2025-11-25"): v2025.CreateMessageResult,
        # 2026-07-28: none (no server-to-client requests at this version)
    }
)
"""Results clients send, keyed by the originating server request's (method, version)."""


# --- Direction-specific method sets ---

SPEC_CLIENT_METHODS: Final[frozenset[str]] = frozenset(m for m, _ in CLIENT_REQUESTS)
"""Spec request methods a client may send (any version); the server-side spec-method discriminator."""

SPEC_CLIENT_NOTIFICATION_METHODS: Final[frozenset[str]] = frozenset(m for m, _ in CLIENT_NOTIFICATIONS)
"""Spec notification methods a client may send (any version); the server-side spec-method discriminator."""


# --- Monolith maps ---

MONOLITH_REQUESTS: Final[Mapping[str, type[types.Request[Any, Any]]]] = MappingProxyType(
    {
        "completion/complete": types.CompleteRequest,
        "elicitation/create": types.ElicitRequest,
        "initialize": types.InitializeRequest,
        "logging/setLevel": types.SetLevelRequest,
        "ping": types.PingRequest,
        "prompts/get": types.GetPromptRequest,
        "prompts/list": types.ListPromptsRequest,
        "resources/list": types.ListResourcesRequest,
        "resources/read": types.ReadResourceRequest,
        "resources/subscribe": types.SubscribeRequest,
        "resources/templates/list": types.ListResourceTemplatesRequest,
        "resources/unsubscribe": types.UnsubscribeRequest,
        "roots/list": types.ListRootsRequest,
        "sampling/createMessage": types.CreateMessageRequest,
        "server/discover": types.DiscoverRequest,
        "subscriptions/listen": types.SubscriptionsListenRequest,
        "tools/call": types.CallToolRequest,
        "tools/list": types.ListToolsRequest,
    }
)
"""Monolith request model per method, both directions."""

MONOLITH_NOTIFICATIONS: Final[Mapping[str, type[types.Notification[Any, Any]]]] = MappingProxyType(
    {
        "notifications/cancelled": types.CancelledNotification,
        "notifications/elicitation/complete": types.ElicitCompleteNotification,
        "notifications/initialized": types.InitializedNotification,
        "notifications/message": types.LoggingMessageNotification,
        "notifications/progress": types.ProgressNotification,
        "notifications/prompts/list_changed": types.PromptListChangedNotification,
        "notifications/resources/list_changed": types.ResourceListChangedNotification,
        "notifications/resources/updated": types.ResourceUpdatedNotification,
        "notifications/roots/list_changed": types.RootsListChangedNotification,
        "notifications/subscriptions/acknowledged": types.SubscriptionsAcknowledgedNotification,
        "notifications/tools/list_changed": types.ToolListChangedNotification,
    }
)
"""Monolith notification model per method, both directions."""

MONOLITH_RESULTS: Final[Mapping[str, type[types.Result] | UnionType]] = MappingProxyType(
    {
        "completion/complete": types.CompleteResult,
        "elicitation/create": types.ElicitResult,
        "initialize": types.InitializeResult,
        "logging/setLevel": types.EmptyResult,
        "ping": types.EmptyResult,
        "prompts/get": types.GetPromptResult | types.InputRequiredResult,
        "prompts/list": types.ListPromptsResult,
        "resources/list": types.ListResourcesResult,
        "resources/read": types.ReadResourceResult | types.InputRequiredResult,
        "resources/subscribe": types.EmptyResult,
        "resources/templates/list": types.ListResourceTemplatesResult,
        "resources/unsubscribe": types.EmptyResult,
        "roots/list": types.ListRootsResult,
        # Arm order load-bearing: a single-block body satisfies both arms and
        # smart-union ties resolve leftmost. Pinned by tests/types/test_methods.py.
        "sampling/createMessage": types.CreateMessageResult | types.CreateMessageResultWithTools,
        "server/discover": types.DiscoverResult,
        "subscriptions/listen": types.SubscriptionsListenResult,
        "tools/call": types.CallToolResult | types.InputRequiredResult,
        "tools/list": types.ListToolsResult,
    }
)
"""Monolith result model (or two-arm union) per request method."""


# --- Cacheable methods ---

CacheableMethod = Literal[
    "prompts/list",
    "resources/list",
    "resources/read",
    "resources/templates/list",
    "server/discover",
    "tools/list",
]
"""Methods whose results carry `ttlMs`/`cacheScope`; hand-written Literal, welded to `CACHEABLE_METHODS` by tests."""

CACHEABLE_METHODS: Final[frozenset[str]] = frozenset(
    method
    for method, row in MONOLITH_RESULTS.items()
    if any(issubclass(arm, types.CacheableResult) for arm in (get_args(row) if isinstance(row, UnionType) else (row,)))
)
"""Runtime mirror of `CacheableMethod`, derived from `MONOLITH_RESULTS`."""


# --- Parse functions ---

# Envelope stubs merged into bodies for surface validation (surface classes are full frames).
_REQUEST_STUB: Final[Mapping[str, Any]] = MappingProxyType({"jsonrpc": "2.0", "id": 0})
_NOTIFICATION_STUB: Final[Mapping[str, Any]] = MappingProxyType({"jsonrpc": "2.0"})


def _check_known_version(version: str) -> None:
    """Raise ValueError for unknown `version` so a typo cannot silently gate every method."""
    if version not in KNOWN_PROTOCOL_VERSIONS:
        raise ValueError(f"version must be a known protocol version, got {version!r}")


def _body(method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a JSON-RPC body, omitting `params` when None."""
    body: dict[str, Any] = {"method": method}
    if params is not None:
        body["params"] = params
    return body


@cache
def _adapter(target: type[BaseModel] | UnionType) -> TypeAdapter[Any]:
    return TypeAdapter(target)


_MonolithT = TypeVar("_MonolithT")


def _monolith_row(monolith: Mapping[str, _MonolithT], method: str) -> _MonolithT:
    """Look up `method` in `monolith`, raising RuntimeError on miss.

    Not KeyError: the surface row already matched, so a miss is inconsistent
    extension maps and must not be caught by the session's `except KeyError` gate.
    """
    try:
        return monolith[method]
    except KeyError:
        raise RuntimeError(f"inconsistent extension maps: surface defines {method!r} but monolith does not") from None


def validate_client_request(
    method: str,
    version: str,
    params: Mapping[str, Any] | None,
    *,
    surface: Mapping[tuple[str, str], type[BaseModel]] = CLIENT_REQUESTS,
) -> None:
    """Validate a client request against `surface` only.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface` (the version gate).
        pydantic.ValidationError: body fails surface validation.
    """
    _check_known_version(version)
    surface[(method, version)].model_validate({**_REQUEST_STUB, **_body(method, params)}, by_name=False)


def parse_client_request(
    method: str,
    version: str,
    params: Mapping[str, Any] | None,
    *,
    surface: Mapping[tuple[str, str], type[BaseModel]] = CLIENT_REQUESTS,
    monolith: Mapping[str, type[types.Request[Any, Any]]] = MONOLITH_REQUESTS,
) -> types.Request[Any, Any]:
    """Validate a client request against `surface`, then parse and return its `monolith` model.

    Args:
        surface: `(method, version)` to wire-type map; the version-gate lookup
            and (per-schema-era) shape check run against this. Pass an extended
            map to admit custom methods.
        monolith: `method` to version-free model map; the returned instance is
            parsed from this row. Must cover every method `surface` admits.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface` (the version gate).
        pydantic.ValidationError: body fails surface or monolith validation.
        RuntimeError: surface matched but `method` has no monolith row.
    """
    validate_client_request(method, version, params, surface=surface)
    return _monolith_row(monolith, method).model_validate(_body(method, params), by_name=False)


def parse_server_request(
    method: str,
    version: str,
    params: Mapping[str, Any] | None,
    *,
    surface: Mapping[tuple[str, str], type[BaseModel]] = SERVER_REQUESTS,
    monolith: Mapping[str, type[types.Request[Any, Any]]] = MONOLITH_REQUESTS,
) -> types.Request[Any, Any]:
    """Validate a server request against `surface`, then parse and return its `monolith` model.

    Args:
        surface: `(method, version)` to wire-type map; the version-gate lookup
            and (per-schema-era) shape check run against this. Pass an extended
            map to admit custom methods.
        monolith: `method` to version-free model map; the returned instance is
            parsed from this row. Must cover every method `surface` admits.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface` (the version gate).
        pydantic.ValidationError: body fails surface or monolith validation.
        RuntimeError: surface matched but `method` has no monolith row.
    """
    _check_known_version(version)
    surface_type = surface[(method, version)]
    surface_type.model_validate({**_REQUEST_STUB, **_body(method, params)}, by_name=False)
    return _monolith_row(monolith, method).model_validate(_body(method, params), by_name=False)


def validate_client_notification(
    method: str,
    version: str,
    params: Mapping[str, Any] | None,
    *,
    surface: Mapping[tuple[str, str], type[BaseModel]] = CLIENT_NOTIFICATIONS,
) -> None:
    """Validate a client notification against `surface` only.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: body fails surface validation.
    """
    _check_known_version(version)
    surface[(method, version)].model_validate({**_NOTIFICATION_STUB, **_body(method, params)}, by_name=False)


def parse_client_notification(
    method: str,
    version: str,
    params: Mapping[str, Any] | None,
    *,
    surface: Mapping[tuple[str, str], type[BaseModel]] = CLIENT_NOTIFICATIONS,
    monolith: Mapping[str, type[types.Notification[Any, Any]]] = MONOLITH_NOTIFICATIONS,
) -> types.Notification[Any, Any]:
    """Validate a client notification against `surface`, then parse and return its `monolith` model.

    Args:
        surface: `(method, version)` to wire-type map; the version-gate lookup
            and (per-schema-era) shape check run against this. Pass an extended
            map to admit custom methods.
        monolith: `method` to version-free model map; the returned instance is
            parsed from this row. Must cover every method `surface` admits.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: body fails surface or monolith validation.
        RuntimeError: surface matched but `method` has no monolith row.
    """
    validate_client_notification(method, version, params, surface=surface)
    return _monolith_row(monolith, method).model_validate(_body(method, params), by_name=False)


def parse_server_notification(
    method: str,
    version: str,
    params: Mapping[str, Any] | None,
    *,
    surface: Mapping[tuple[str, str], type[BaseModel]] = SERVER_NOTIFICATIONS,
    monolith: Mapping[str, type[types.Notification[Any, Any]]] = MONOLITH_NOTIFICATIONS,
) -> types.Notification[Any, Any]:
    """Validate a server notification against `surface`, then parse and return its `monolith` model.

    Args:
        surface: `(method, version)` to wire-type map; the version-gate lookup
            and (per-schema-era) shape check run against this. Pass an extended
            map to admit custom methods.
        monolith: `method` to version-free model map; the returned instance is
            parsed from this row. Must cover every method `surface` admits.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: body fails surface or monolith validation.
        RuntimeError: surface matched but `method` has no monolith row.
    """
    _check_known_version(version)
    surface_type = surface[(method, version)]
    surface_type.model_validate({**_NOTIFICATION_STUB, **_body(method, params)}, by_name=False)
    return _monolith_row(monolith, method).model_validate(_body(method, params), by_name=False)


def serialize_server_result(
    method: str,
    version: str,
    data: Mapping[str, Any],
    *,
    surface: Mapping[tuple[str, str], type[BaseModel] | UnionType] = SERVER_RESULTS,
) -> dict[str, Any]:
    """Validate `data` against `surface` and return its surface-shaped dump.

    The surface model carries `extra="ignore"`, so fields not in `version`'s
    schema are dropped from the returned dict.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: result fails surface validation.
    """
    _check_known_version(version)
    adapter = _adapter(surface[(method, version)])
    return adapter.dump_python(
        adapter.validate_python(data, by_name=False), by_alias=True, mode="json", exclude_none=True
    )


def validate_server_result(
    method: str,
    version: str,
    data: Mapping[str, Any],
    *,
    surface: Mapping[tuple[str, str], type[BaseModel] | UnionType] = SERVER_RESULTS,
) -> None:
    """Validate a server result against `surface` only.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: result fails surface validation.
    """
    serialize_server_result(method, version, data, surface=surface)


def parse_server_result(
    method: str,
    version: str,
    data: Mapping[str, Any],
    *,
    surface: Mapping[tuple[str, str], type[BaseModel] | UnionType] = SERVER_RESULTS,
    monolith: Mapping[str, type[types.Result] | UnionType] = MONOLITH_RESULTS,
) -> types.Result:
    """Validate a server result against `surface`, then parse and return its `monolith` model.

    Args:
        surface: `(method, version)` to wire-type map; the version-gate lookup
            and (per-schema-era) shape check run against this. Pass an extended
            map to admit custom methods.
        monolith: `method` to version-free model map; the returned instance is
            parsed from this row. Must cover every method `surface` admits.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: result fails surface or monolith validation.
        RuntimeError: surface matched but `method` has no monolith row.
    """
    validate_server_result(method, version, data, surface=surface)
    result: types.Result = _adapter(_monolith_row(monolith, method)).validate_python(data, by_name=False)
    return result


def validate_client_result(
    method: str,
    version: str,
    data: Mapping[str, Any],
    *,
    surface: Mapping[tuple[str, str], type[BaseModel] | UnionType] = CLIENT_RESULTS,
) -> None:
    """Validate a client result against `surface` only.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: result fails surface validation.
    """
    _check_known_version(version)
    _adapter(surface[(method, version)]).validate_python(data, by_name=False)


def parse_client_result(
    method: str,
    version: str,
    data: Mapping[str, Any],
    *,
    surface: Mapping[tuple[str, str], type[BaseModel] | UnionType] = CLIENT_RESULTS,
    monolith: Mapping[str, type[types.Result] | UnionType] = MONOLITH_RESULTS,
) -> types.Result:
    """Validate a client result against `surface`, then parse and return its `monolith` model.

    Args:
        surface: `(method, version)` to wire-type map; the version-gate lookup
            and (per-schema-era) shape check run against this. Pass an extended
            map to admit custom methods.
        monolith: `method` to version-free model map; the returned instance is
            parsed from this row. Must cover every method `surface` admits.

    Raises:
        ValueError: `version` is not a known protocol version.
        KeyError: `(method, version)` is not in `surface`.
        pydantic.ValidationError: result fails surface or monolith validation.
        RuntimeError: surface matched but `method` has no monolith row.
    """
    validate_client_result(method, version, data, surface=surface)
    result: types.Result = _adapter(_monolith_row(monolith, method)).validate_python(data, by_name=False)
    return result
