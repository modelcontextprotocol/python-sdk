"""Per-version method maps and parse/serialize functions for MCP traffic.

This module is supported public API; the `mcp_types._v*` packages it draws on
are internal validators and not for direct import.

Surface maps key `(method, version)` to per-version wire types (key absence is
the version gate; shape validation is per schema era, i.e. 2025-11-25 for every
pre-2026 version and 2026-07-28 for 2026). Monolith maps key `method` to the
version-free `mcp_types` models user code receives.

The surface maps do not import the per-version wire packages up front: each
`mcp_types._v*` package is ~100 ms of pydantic model construction and a
connection negotiates exactly one version, so a row's package is imported the
first time that row is read (see `_LazyWireMap`)."""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator, Mapping
from functools import cache
from importlib import import_module
from types import MappingProxyType, ModuleType, UnionType
from typing import TYPE_CHECKING, Any, Final, Literal, NamedTuple, TypeGuard, TypeVar, cast, get_args

from pydantic import BaseModel, TypeAdapter

import mcp_types as types
from mcp_types import jsonrpc
from mcp_types.version import KNOWN_PROTOCOL_VERSIONS

if TYPE_CHECKING:
    # The wire packages are imported by module name at runtime (below), which a
    # static bundler (PyInstaller and friends) cannot see; these compiled-in but
    # never-executed imports keep the dependency discoverable for such tools
    # (else add the packages to the bundler's hidden imports; see
    # docs/advanced/import-cost.md).
    import mcp_types._v2025_11_25 as _v2025_11_25
    import mcp_types._v2026_07_28 as _v2026_07_28

    _WIRE_PACKAGE_MODULES: Final = (_v2025_11_25, _v2026_07_28)

__all__ = [
    "CACHEABLE_METHODS",
    "CLIENT_NOTIFICATIONS",
    "CLIENT_REQUESTS",
    "CLIENT_RESULTS",
    "CacheableMethod",
    "INPUT_REQUIRED_METHODS",
    "MONOLITH_NOTIFICATIONS",
    "MONOLITH_REQUESTS",
    "MONOLITH_RESULTS",
    "SERVER_NOTIFICATIONS",
    "SERVER_REQUESTS",
    "SERVER_RESULTS",
    "SPEC_CLIENT_METHODS",
    "SPEC_CLIENT_NOTIFICATION_METHODS",
    "WarmReport",
    "is_input_required",
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
    "warm",
]


# --- Lazy per-version wire package loading ---

_WIRE_PACKAGE_BY_VERSION: Final[Mapping[str, str]] = MappingProxyType(
    {
        # Every pre-2026 version validates against the 2025-11-25 schema era.
        "2024-11-05": "mcp_types._v2025_11_25",
        "2025-03-26": "mcp_types._v2025_11_25",
        "2025-06-18": "mcp_types._v2025_11_25",
        "2025-11-25": "mcp_types._v2025_11_25",
        "2026-07-28": "mcp_types._v2026_07_28",
    }
)
"""The internal wire package holding each protocol version's surface types (by module name)."""


@cache
def _wire_package(version: str) -> ModuleType:
    """Import (once) and return the generated wire package that validates `version`.

    Deliberately lazy - the documented exception to top-of-module imports: each
    `mcp_types._v*` package costs ~100 ms of pydantic model construction, and a
    process typically speaks a single negotiated version, so a package loads the
    first time one of its surface rows is read rather than at `import` time.
    """
    return import_module(_WIRE_PACKAGE_BY_VERSION[version])


class _LazyWireMap(Mapping[tuple[str, str], Any]):
    """`(method, version)` -> wire-row map that resolves rows on first read.

    A row is recorded as the attribute name of its wire type inside its
    version's package (static data); reading the row imports that package via
    `_wire_package` and caches the resolved value. Key operations (`in`,
    iteration, `len`) never import; whole-map operations (`values()`,
    `items()`, `==`, `repr()`) resolve every row.

    Public surface maps are this class wrapped in `MappingProxyType`, so their
    type (`mappingproxy`), read-only behaviour and repr are identical to a
    proxied dict of the resolved rows.
    """

    __slots__ = ("_names", "_rows")

    def __init__(self, names: dict[tuple[str, str], str]) -> None:
        unmapped = {version for _, version in names} - _WIRE_PACKAGE_BY_VERSION.keys()
        if unmapped:
            raise ValueError(f"no wire package registered for protocol version(s) {sorted(unmapped)}")
        self._names = names
        self._rows: dict[tuple[str, str], Any] = {}

    def __getitem__(self, key: tuple[str, str]) -> Any:
        try:
            return self._rows[key]
        except KeyError:
            pass
        name = self._names[key]  # KeyError here is the version gate.
        row = self._rows[key] = getattr(_wire_package(key[1]), name)
        return row

    def __contains__(self, key: object) -> bool:
        return key in self._names

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._names)

    def __reversed__(self) -> Iterator[tuple[str, str]]:
        return reversed(self._names)

    def __len__(self) -> int:
        return len(self._names)

    def __repr__(self) -> str:
        return repr(dict(self))

    def copy(self) -> dict[tuple[str, str], Any]:
        """A resolved plain-dict copy, matching `mappingproxy.copy()` over a dict."""
        return dict(self)

    def __or__(self, other: Mapping[Any, Any]) -> dict[Any, Any]:
        return {**self, **other}

    def __ror__(self, other: Mapping[Any, Any]) -> dict[Any, Any]:
        return {**other, **self}


def _surface(names: dict[tuple[str, str], str]) -> MappingProxyType[tuple[str, str], Any]:
    """Build a read-only surface map from `(method, version)` -> wire-type name rows."""
    return MappingProxyType(_LazyWireMap(names))


# --- Surface maps: client-to-server ---

CLIENT_REQUESTS: Final[Mapping[tuple[str, str], type[BaseModel]]] = _surface(
    {
        # 2024-11-05
        ("completion/complete", "2024-11-05"): "CompleteRequest",
        ("initialize", "2024-11-05"): "InitializeRequest",
        ("logging/setLevel", "2024-11-05"): "SetLevelRequest",
        ("ping", "2024-11-05"): "PingRequest",
        ("prompts/get", "2024-11-05"): "GetPromptRequest",
        ("prompts/list", "2024-11-05"): "ListPromptsRequest",
        ("resources/list", "2024-11-05"): "ListResourcesRequest",
        ("resources/read", "2024-11-05"): "ReadResourceRequest",
        ("resources/subscribe", "2024-11-05"): "SubscribeRequest",
        ("resources/templates/list", "2024-11-05"): "ListResourceTemplatesRequest",
        ("resources/unsubscribe", "2024-11-05"): "UnsubscribeRequest",
        ("tools/call", "2024-11-05"): "CallToolRequest",
        ("tools/list", "2024-11-05"): "ListToolsRequest",
        # 2025-03-26
        ("completion/complete", "2025-03-26"): "CompleteRequest",
        ("initialize", "2025-03-26"): "InitializeRequest",
        ("logging/setLevel", "2025-03-26"): "SetLevelRequest",
        ("ping", "2025-03-26"): "PingRequest",
        ("prompts/get", "2025-03-26"): "GetPromptRequest",
        ("prompts/list", "2025-03-26"): "ListPromptsRequest",
        ("resources/list", "2025-03-26"): "ListResourcesRequest",
        ("resources/read", "2025-03-26"): "ReadResourceRequest",
        ("resources/subscribe", "2025-03-26"): "SubscribeRequest",
        ("resources/templates/list", "2025-03-26"): "ListResourceTemplatesRequest",
        ("resources/unsubscribe", "2025-03-26"): "UnsubscribeRequest",
        ("tools/call", "2025-03-26"): "CallToolRequest",
        ("tools/list", "2025-03-26"): "ListToolsRequest",
        # 2025-06-18
        ("completion/complete", "2025-06-18"): "CompleteRequest",
        ("initialize", "2025-06-18"): "InitializeRequest",
        ("logging/setLevel", "2025-06-18"): "SetLevelRequest",
        ("ping", "2025-06-18"): "PingRequest",
        ("prompts/get", "2025-06-18"): "GetPromptRequest",
        ("prompts/list", "2025-06-18"): "ListPromptsRequest",
        ("resources/list", "2025-06-18"): "ListResourcesRequest",
        ("resources/read", "2025-06-18"): "ReadResourceRequest",
        ("resources/subscribe", "2025-06-18"): "SubscribeRequest",
        ("resources/templates/list", "2025-06-18"): "ListResourceTemplatesRequest",
        ("resources/unsubscribe", "2025-06-18"): "UnsubscribeRequest",
        ("tools/call", "2025-06-18"): "CallToolRequest",
        ("tools/list", "2025-06-18"): "ListToolsRequest",
        # 2025-11-25 (tasks/* deliberately absent)
        ("completion/complete", "2025-11-25"): "CompleteRequest",
        ("initialize", "2025-11-25"): "InitializeRequest",
        ("logging/setLevel", "2025-11-25"): "SetLevelRequest",
        ("ping", "2025-11-25"): "PingRequest",
        ("prompts/get", "2025-11-25"): "GetPromptRequest",
        ("prompts/list", "2025-11-25"): "ListPromptsRequest",
        ("resources/list", "2025-11-25"): "ListResourcesRequest",
        ("resources/read", "2025-11-25"): "ReadResourceRequest",
        ("resources/subscribe", "2025-11-25"): "SubscribeRequest",
        ("resources/templates/list", "2025-11-25"): "ListResourceTemplatesRequest",
        ("resources/unsubscribe", "2025-11-25"): "UnsubscribeRequest",
        ("tools/call", "2025-11-25"): "CallToolRequest",
        ("tools/list", "2025-11-25"): "ListToolsRequest",
        # 2026-07-28 (lifecycle, logging, subscribe pair removed; discover/listen added)
        ("completion/complete", "2026-07-28"): "CompleteRequest",
        ("prompts/get", "2026-07-28"): "GetPromptRequest",
        ("prompts/list", "2026-07-28"): "ListPromptsRequest",
        ("resources/list", "2026-07-28"): "ListResourcesRequest",
        ("resources/read", "2026-07-28"): "ReadResourceRequest",
        ("resources/templates/list", "2026-07-28"): "ListResourceTemplatesRequest",
        ("server/discover", "2026-07-28"): "DiscoverRequest",
        ("subscriptions/listen", "2026-07-28"): "SubscriptionsListenRequest",
        ("tools/call", "2026-07-28"): "CallToolRequest",
        ("tools/list", "2026-07-28"): "ListToolsRequest",
    }
)

CLIENT_NOTIFICATIONS: Final[Mapping[tuple[str, str], type[BaseModel]]] = _surface(
    {
        # 2024-11-05
        ("notifications/cancelled", "2024-11-05"): "CancelledNotification",
        ("notifications/initialized", "2024-11-05"): "InitializedNotification",
        ("notifications/progress", "2024-11-05"): "ProgressNotification",
        ("notifications/roots/list_changed", "2024-11-05"): "RootsListChangedNotification",
        # 2025-03-26
        ("notifications/cancelled", "2025-03-26"): "CancelledNotification",
        ("notifications/initialized", "2025-03-26"): "InitializedNotification",
        ("notifications/progress", "2025-03-26"): "ProgressNotification",
        ("notifications/roots/list_changed", "2025-03-26"): "RootsListChangedNotification",
        # 2025-06-18
        ("notifications/cancelled", "2025-06-18"): "CancelledNotification",
        ("notifications/initialized", "2025-06-18"): "InitializedNotification",
        ("notifications/progress", "2025-06-18"): "ProgressNotification",
        ("notifications/roots/list_changed", "2025-06-18"): "RootsListChangedNotification",
        # 2025-11-25 (tasks/status deliberately absent)
        ("notifications/cancelled", "2025-11-25"): "CancelledNotification",
        ("notifications/initialized", "2025-11-25"): "InitializedNotification",
        ("notifications/progress", "2025-11-25"): "ProgressNotification",
        ("notifications/roots/list_changed", "2025-11-25"): "RootsListChangedNotification",
        # 2026-07-28 (initialized, progress and roots/list_changed removed)
        ("notifications/cancelled", "2026-07-28"): "CancelledNotification",
    }
)


# --- Surface maps: server-to-client ---

SERVER_REQUESTS: Final[Mapping[tuple[str, str], type[BaseModel]]] = _surface(
    {
        # 2024-11-05
        ("ping", "2024-11-05"): "PingRequest",
        ("roots/list", "2024-11-05"): "ListRootsRequest",
        ("sampling/createMessage", "2024-11-05"): "CreateMessageRequest",
        # 2025-03-26
        ("ping", "2025-03-26"): "PingRequest",
        ("roots/list", "2025-03-26"): "ListRootsRequest",
        ("sampling/createMessage", "2025-03-26"): "CreateMessageRequest",
        # 2025-06-18 (adds elicitation/create)
        ("elicitation/create", "2025-06-18"): "ElicitRequest",
        ("ping", "2025-06-18"): "PingRequest",
        ("roots/list", "2025-06-18"): "ListRootsRequest",
        ("sampling/createMessage", "2025-06-18"): "CreateMessageRequest",
        # 2025-11-25 (tasks/* deliberately absent)
        ("elicitation/create", "2025-11-25"): "ElicitRequest",
        ("ping", "2025-11-25"): "PingRequest",
        ("roots/list", "2025-11-25"): "ListRootsRequest",
        ("sampling/createMessage", "2025-11-25"): "CreateMessageRequest",
        # 2026-07-28: none (schema defines no ServerRequest union)
    }
)

SERVER_NOTIFICATIONS: Final[Mapping[tuple[str, str], type[BaseModel]]] = _surface(
    {
        # 2024-11-05
        ("notifications/cancelled", "2024-11-05"): "CancelledNotification",
        ("notifications/message", "2024-11-05"): "LoggingMessageNotification",
        ("notifications/progress", "2024-11-05"): "ProgressNotification",
        ("notifications/prompts/list_changed", "2024-11-05"): "PromptListChangedNotification",
        ("notifications/resources/list_changed", "2024-11-05"): "ResourceListChangedNotification",
        ("notifications/resources/updated", "2024-11-05"): "ResourceUpdatedNotification",
        ("notifications/tools/list_changed", "2024-11-05"): "ToolListChangedNotification",
        # 2025-03-26
        ("notifications/cancelled", "2025-03-26"): "CancelledNotification",
        ("notifications/message", "2025-03-26"): "LoggingMessageNotification",
        ("notifications/progress", "2025-03-26"): "ProgressNotification",
        ("notifications/prompts/list_changed", "2025-03-26"): "PromptListChangedNotification",
        ("notifications/resources/list_changed", "2025-03-26"): "ResourceListChangedNotification",
        ("notifications/resources/updated", "2025-03-26"): "ResourceUpdatedNotification",
        ("notifications/tools/list_changed", "2025-03-26"): "ToolListChangedNotification",
        # 2025-06-18
        ("notifications/cancelled", "2025-06-18"): "CancelledNotification",
        ("notifications/message", "2025-06-18"): "LoggingMessageNotification",
        ("notifications/progress", "2025-06-18"): "ProgressNotification",
        ("notifications/prompts/list_changed", "2025-06-18"): "PromptListChangedNotification",
        ("notifications/resources/list_changed", "2025-06-18"): "ResourceListChangedNotification",
        ("notifications/resources/updated", "2025-06-18"): "ResourceUpdatedNotification",
        ("notifications/tools/list_changed", "2025-06-18"): "ToolListChangedNotification",
        # 2025-11-25 (adds elicitation/complete; tasks/status deliberately absent)
        ("notifications/cancelled", "2025-11-25"): "CancelledNotification",
        ("notifications/elicitation/complete", "2025-11-25"): "ElicitationCompleteNotification",
        ("notifications/message", "2025-11-25"): "LoggingMessageNotification",
        ("notifications/progress", "2025-11-25"): "ProgressNotification",
        ("notifications/prompts/list_changed", "2025-11-25"): "PromptListChangedNotification",
        ("notifications/resources/list_changed", "2025-11-25"): "ResourceListChangedNotification",
        ("notifications/resources/updated", "2025-11-25"): "ResourceUpdatedNotification",
        ("notifications/tools/list_changed", "2025-11-25"): "ToolListChangedNotification",
        # 2026-07-28 (adds subscriptions/acknowledged; elicitation/complete removed)
        ("notifications/cancelled", "2026-07-28"): "CancelledNotification",
        ("notifications/message", "2026-07-28"): "LoggingMessageNotification",
        ("notifications/progress", "2026-07-28"): "ProgressNotification",
        ("notifications/prompts/list_changed", "2026-07-28"): "PromptListChangedNotification",
        ("notifications/resources/list_changed", "2026-07-28"): "ResourceListChangedNotification",
        ("notifications/resources/updated", "2026-07-28"): "ResourceUpdatedNotification",
        ("notifications/subscriptions/acknowledged", "2026-07-28"): "SubscriptionsAcknowledgedNotification",
        ("notifications/tools/list_changed", "2026-07-28"): "ToolListChangedNotification",
    }
)


# --- Surface maps: results ---

SERVER_RESULTS: Final[Mapping[tuple[str, str], type[BaseModel] | UnionType]] = _surface(
    {
        # 2024-11-05
        ("completion/complete", "2024-11-05"): "CompleteResult",
        ("initialize", "2024-11-05"): "InitializeResult",
        ("logging/setLevel", "2024-11-05"): "EmptyResult",
        ("ping", "2024-11-05"): "EmptyResult",
        ("prompts/get", "2024-11-05"): "GetPromptResult",
        ("prompts/list", "2024-11-05"): "ListPromptsResult",
        ("resources/list", "2024-11-05"): "ListResourcesResult",
        ("resources/read", "2024-11-05"): "ReadResourceResult",
        ("resources/subscribe", "2024-11-05"): "EmptyResult",
        ("resources/templates/list", "2024-11-05"): "ListResourceTemplatesResult",
        ("resources/unsubscribe", "2024-11-05"): "EmptyResult",
        ("tools/call", "2024-11-05"): "CallToolResult",
        ("tools/list", "2024-11-05"): "ListToolsResult",
        # 2025-03-26
        ("completion/complete", "2025-03-26"): "CompleteResult",
        ("initialize", "2025-03-26"): "InitializeResult",
        ("logging/setLevel", "2025-03-26"): "EmptyResult",
        ("ping", "2025-03-26"): "EmptyResult",
        ("prompts/get", "2025-03-26"): "GetPromptResult",
        ("prompts/list", "2025-03-26"): "ListPromptsResult",
        ("resources/list", "2025-03-26"): "ListResourcesResult",
        ("resources/read", "2025-03-26"): "ReadResourceResult",
        ("resources/subscribe", "2025-03-26"): "EmptyResult",
        ("resources/templates/list", "2025-03-26"): "ListResourceTemplatesResult",
        ("resources/unsubscribe", "2025-03-26"): "EmptyResult",
        ("tools/call", "2025-03-26"): "CallToolResult",
        ("tools/list", "2025-03-26"): "ListToolsResult",
        # 2025-06-18
        ("completion/complete", "2025-06-18"): "CompleteResult",
        ("initialize", "2025-06-18"): "InitializeResult",
        ("logging/setLevel", "2025-06-18"): "EmptyResult",
        ("ping", "2025-06-18"): "EmptyResult",
        ("prompts/get", "2025-06-18"): "GetPromptResult",
        ("prompts/list", "2025-06-18"): "ListPromptsResult",
        ("resources/list", "2025-06-18"): "ListResourcesResult",
        ("resources/read", "2025-06-18"): "ReadResourceResult",
        ("resources/subscribe", "2025-06-18"): "EmptyResult",
        ("resources/templates/list", "2025-06-18"): "ListResourceTemplatesResult",
        ("resources/unsubscribe", "2025-06-18"): "EmptyResult",
        ("tools/call", "2025-06-18"): "CallToolResult",
        ("tools/list", "2025-06-18"): "ListToolsResult",
        # 2025-11-25
        ("completion/complete", "2025-11-25"): "CompleteResult",
        ("initialize", "2025-11-25"): "InitializeResult",
        ("logging/setLevel", "2025-11-25"): "EmptyResult",
        ("ping", "2025-11-25"): "EmptyResult",
        ("prompts/get", "2025-11-25"): "GetPromptResult",
        ("prompts/list", "2025-11-25"): "ListPromptsResult",
        ("resources/list", "2025-11-25"): "ListResourcesResult",
        ("resources/read", "2025-11-25"): "ReadResourceResult",
        ("resources/subscribe", "2025-11-25"): "EmptyResult",
        ("resources/templates/list", "2025-11-25"): "ListResourceTemplatesResult",
        ("resources/unsubscribe", "2025-11-25"): "EmptyResult",
        ("tools/call", "2025-11-25"): "CallToolResult",
        ("tools/list", "2025-11-25"): "ListToolsResult",
        # 2026-07-28 (dual-result rows use the version's union aliases)
        ("completion/complete", "2026-07-28"): "CompleteResult",
        ("prompts/get", "2026-07-28"): "AnyGetPromptResult",
        ("prompts/list", "2026-07-28"): "ListPromptsResult",
        ("resources/list", "2026-07-28"): "ListResourcesResult",
        ("resources/read", "2026-07-28"): "AnyReadResourceResult",
        ("resources/templates/list", "2026-07-28"): "ListResourceTemplatesResult",
        ("server/discover", "2026-07-28"): "DiscoverResult",
        ("subscriptions/listen", "2026-07-28"): "SubscriptionsListenResult",
        ("tools/call", "2026-07-28"): "AnyCallToolResult",
        ("tools/list", "2026-07-28"): "ListToolsResult",
    }
)
"""Results servers send, keyed by the originating client request's (method, version)."""

CLIENT_RESULTS: Final[Mapping[tuple[str, str], type[BaseModel] | UnionType]] = _surface(
    {
        # 2024-11-05
        ("ping", "2024-11-05"): "EmptyResult",
        ("roots/list", "2024-11-05"): "ListRootsResult",
        ("sampling/createMessage", "2024-11-05"): "CreateMessageResult",
        # 2025-03-26
        ("ping", "2025-03-26"): "EmptyResult",
        ("roots/list", "2025-03-26"): "ListRootsResult",
        ("sampling/createMessage", "2025-03-26"): "CreateMessageResult",
        # 2025-06-18
        ("elicitation/create", "2025-06-18"): "ElicitResult",
        ("ping", "2025-06-18"): "EmptyResult",
        ("roots/list", "2025-06-18"): "ListRootsResult",
        ("sampling/createMessage", "2025-06-18"): "CreateMessageResult",
        # 2025-11-25
        ("elicitation/create", "2025-11-25"): "ElicitResult",
        ("ping", "2025-11-25"): "EmptyResult",
        ("roots/list", "2025-11-25"): "ListRootsResult",
        ("sampling/createMessage", "2025-11-25"): "CreateMessageResult",
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

INPUT_REQUIRED_METHODS: Final[frozenset[str]] = frozenset(
    method
    for method, row in MONOLITH_RESULTS.items()
    if any(
        issubclass(arm, types.InputRequiredResult) for arm in (get_args(row) if isinstance(row, UnionType) else (row,))
    )
)
"""Methods whose results may be `InputRequiredResult`, derived from `MONOLITH_RESULTS`."""


def is_input_required(result: object) -> TypeGuard[types.InputRequiredResult | dict[str, Any]]:
    """True when `result` is an `input_required` interim result, typed or wire-shaped."""
    if isinstance(result, types.InputRequiredResult):
        return True
    return isinstance(result, Mapping) and cast("Mapping[str, Any]", result).get("resultType") == "input_required"


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


# --- Opt-in prewarm ---

_ALL_SURFACES: Final = (
    CLIENT_REQUESTS,
    CLIENT_NOTIFICATIONS,
    CLIENT_RESULTS,
    SERVER_REQUESTS,
    SERVER_NOTIFICATIONS,
    SERVER_RESULTS,
)
"""Every surface map, for `warm(version)` (rows of one version import one wire package)."""

_ALL_MONOLITHS: Final = (MONOLITH_REQUESTS, MONOLITH_NOTIFICATIONS, MONOLITH_RESULTS)
"""Every monolith map, for `warm()`."""


class WarmReport(NamedTuple):
    """What one `warm()` call built (already-built work is skipped and not counted)."""

    models: int
    """Deferred model classes whose validators this call built."""

    adapters: int
    """Deferred TypeAdapters (union / routing adapters) this call built."""

    elapsed_ms: float
    """Wall-clock milliseconds the call took."""


def _model_classes(target: object) -> Iterator[type[BaseModel]]:
    """The model classes in a surface/monolith row: the class itself, or a union's arms."""
    if isinstance(target, type):
        if issubclass(target, BaseModel):
            yield target
        return
    for arg in get_args(target):
        yield from _model_classes(arg)


def _warm_models(rows: Iterable[object]) -> int:
    """Complete every not-yet-built model class among `rows`; return how many were built."""
    built = 0
    for row in rows:
        for cls in _model_classes(row):
            if not cls.__pydantic_complete__:
                cls.model_rebuild()
                built += 1
    return built


def _warm_adapter(adapter: TypeAdapter[Any]) -> int:
    """Build a deferred TypeAdapter's validator if it is not built yet; return 0 or 1."""
    return 0 if adapter.rebuild() is None else 1


def warm(version: str | None = None, *, everything: bool = False) -> WarmReport:
    """Build the SDK's deferred validators up front, before the first message needs them.

    Importing the SDK stays fast because pydantic validators build on first use
    and each protocol version's wire schemas load with the first message parsed
    at that version. A long-running host that would rather pay that once, at
    startup, calls this from a startup hook; nothing in the SDK calls it, and
    steady-state behaviour is identical either way.

    * `warm()` builds the version-independent set: the monolith `mcp_types`
      models a session routes through, the JSON-RPC envelopes and the
      module-level union adapters.
    * `warm(version)` additionally imports that protocol version's wire
      package and builds its routing surface (the wire models and the cached
      adapters a connection at that version routes through).
    * `warm(everything=True)` does that for every known protocol version.

    Model classes are completed before the adapters that reference them are
    built, so no schema is generated twice; anything already built is skipped,
    so the call is idempotent and repeat calls are cheap.

    Args:
        version: The protocol version whose routing surface to build too.
        everything: Warm every known protocol version (benchmarks, tests).

    Returns:
        Counts of what this call built and the milliseconds it took.

    Raises:
        ValueError: `version` is not a known protocol version.
    """
    started = time.perf_counter()
    versions: list[str] = []
    if everything:
        versions = sorted(KNOWN_PROTOCOL_VERSIONS)
    elif version is not None:
        _check_known_version(version)
        versions = [version]

    # Model classes first (the exported monolith models, the JSON-RPC
    # envelopes, then the wire packages and their routing rows), so the
    # adapters below never generate a referenced model's schema inline.
    models = _warm_models(getattr(types, name) for name in types.__all__)
    models += _warm_models(row for monolith in _ALL_MONOLITHS for row in monolith.values())
    models += _warm_models(get_args(jsonrpc.JSONRPCMessage))
    rows: list[Any] = []
    for warmed_version in versions:
        package = _wire_package(warmed_version)  # imports the package once
        models += _warm_models(vars(package).values())
        for surface in _ALL_SURFACES:
            rows.extend(surface[key] for key in surface if key[1] == warmed_version)
    models += _warm_models(rows)

    adapters = _warm_adapter(jsonrpc.jsonrpc_message_adapter)
    for adapter in (
        types.client_request_adapter,
        types.client_notification_adapter,
        types.client_result_adapter,
        types.server_request_adapter,
        types.server_notification_adapter,
        types.server_result_adapter,
    ):
        adapters += _warm_adapter(adapter)
    for row in rows:
        # `_adapter` is the cached routing-adapter builder the parse/serialize
        # functions use; warming it here (and completing the adapter's own
        # core schema from the now-complete row model) leaves nothing for the
        # first message at that version to build.
        adapters += _warm_adapter(_adapter(row))
    return WarmReport(models=models, adapters=adapters, elapsed_ms=round((time.perf_counter() - started) * 1000, 1))
