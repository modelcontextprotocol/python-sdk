"""Tests for the wire-method maps and two-step parse functions in `mcp.types.methods`."""

import importlib.util
from collections.abc import Mapping
from types import MappingProxyType, UnionType
from typing import Any, get_args

import pydantic
import pytest
from pydantic import BaseModel

import mcp.types as types
import mcp.types.v2025_11_25 as v2025
import mcp.types.v2026_07_28 as v2026
from mcp.shared.version import KNOWN_PROTOCOL_VERSIONS
from mcp.types import methods

# Transcribed from each schema's ClientRequest/ServerRequest/ClientNotification/
# ServerNotification unions, minus the tasks/* family (extensions register those).
EXPECTED_METHODS: dict[str, dict[str, frozenset[str]]] = {
    "2024-11-05": {
        "CLIENT_REQUESTS": frozenset(
            {
                "completion/complete",
                "initialize",
                "logging/setLevel",
                "ping",
                "prompts/get",
                "prompts/list",
                "resources/list",
                "resources/read",
                "resources/subscribe",
                "resources/templates/list",
                "resources/unsubscribe",
                "tools/call",
                "tools/list",
            }
        ),
        "CLIENT_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/initialized",
                "notifications/progress",
                "notifications/roots/list_changed",
            }
        ),
        "SERVER_REQUESTS": frozenset({"ping", "roots/list", "sampling/createMessage"}),
        "SERVER_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/message",
                "notifications/progress",
                "notifications/prompts/list_changed",
                "notifications/resources/list_changed",
                "notifications/resources/updated",
                "notifications/tools/list_changed",
            }
        ),
    },
    "2025-03-26": {
        "CLIENT_REQUESTS": frozenset(
            {
                "completion/complete",
                "initialize",
                "logging/setLevel",
                "ping",
                "prompts/get",
                "prompts/list",
                "resources/list",
                "resources/read",
                "resources/subscribe",
                "resources/templates/list",
                "resources/unsubscribe",
                "tools/call",
                "tools/list",
            }
        ),
        "CLIENT_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/initialized",
                "notifications/progress",
                "notifications/roots/list_changed",
            }
        ),
        "SERVER_REQUESTS": frozenset({"ping", "roots/list", "sampling/createMessage"}),
        "SERVER_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/message",
                "notifications/progress",
                "notifications/prompts/list_changed",
                "notifications/resources/list_changed",
                "notifications/resources/updated",
                "notifications/tools/list_changed",
            }
        ),
    },
    "2025-06-18": {
        "CLIENT_REQUESTS": frozenset(
            {
                "completion/complete",
                "initialize",
                "logging/setLevel",
                "ping",
                "prompts/get",
                "prompts/list",
                "resources/list",
                "resources/read",
                "resources/subscribe",
                "resources/templates/list",
                "resources/unsubscribe",
                "tools/call",
                "tools/list",
            }
        ),
        "CLIENT_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/initialized",
                "notifications/progress",
                "notifications/roots/list_changed",
            }
        ),
        "SERVER_REQUESTS": frozenset({"elicitation/create", "ping", "roots/list", "sampling/createMessage"}),
        "SERVER_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/message",
                "notifications/progress",
                "notifications/prompts/list_changed",
                "notifications/resources/list_changed",
                "notifications/resources/updated",
                "notifications/tools/list_changed",
            }
        ),
    },
    "2025-11-25": {
        "CLIENT_REQUESTS": frozenset(
            {
                "completion/complete",
                "initialize",
                "logging/setLevel",
                "ping",
                "prompts/get",
                "prompts/list",
                "resources/list",
                "resources/read",
                "resources/subscribe",
                "resources/templates/list",
                "resources/unsubscribe",
                "tools/call",
                "tools/list",
            }
        ),
        "CLIENT_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/initialized",
                "notifications/progress",
                "notifications/roots/list_changed",
            }
        ),
        "SERVER_REQUESTS": frozenset({"elicitation/create", "ping", "roots/list", "sampling/createMessage"}),
        "SERVER_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/elicitation/complete",
                "notifications/message",
                "notifications/progress",
                "notifications/prompts/list_changed",
                "notifications/resources/list_changed",
                "notifications/resources/updated",
                "notifications/tools/list_changed",
            }
        ),
    },
    "2026-07-28": {
        "CLIENT_REQUESTS": frozenset(
            {
                "completion/complete",
                "prompts/get",
                "prompts/list",
                "resources/list",
                "resources/read",
                "resources/templates/list",
                "server/discover",
                "subscriptions/listen",
                "tools/call",
                "tools/list",
            }
        ),
        "CLIENT_NOTIFICATIONS": frozenset({"notifications/cancelled"}),
        # No standalone server-to-client request channel at this version.
        "SERVER_REQUESTS": frozenset(),
        "SERVER_NOTIFICATIONS": frozenset(
            {
                "notifications/cancelled",
                "notifications/message",
                "notifications/progress",
                "notifications/prompts/list_changed",
                "notifications/resources/list_changed",
                "notifications/resources/updated",
                "notifications/subscriptions/acknowledged",
                "notifications/tools/list_changed",
            }
        ),
    },
}

# Pinned per (method, version): class identity, or exact arm tuple for unions.
EXPECTED_SERVER_RESULTS: dict[tuple[str, str], type[BaseModel] | tuple[type[BaseModel], ...]] = {
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
    ("completion/complete", "2026-07-28"): v2026.CompleteResult,
    ("prompts/get", "2026-07-28"): (v2026.GetPromptResult, v2026.InputRequiredResult),
    ("prompts/list", "2026-07-28"): v2026.ListPromptsResult,
    ("resources/list", "2026-07-28"): v2026.ListResourcesResult,
    ("resources/read", "2026-07-28"): (v2026.ReadResourceResult, v2026.InputRequiredResult),
    ("resources/templates/list", "2026-07-28"): v2026.ListResourceTemplatesResult,
    ("server/discover", "2026-07-28"): v2026.DiscoverResult,
    ("subscriptions/listen", "2026-07-28"): v2026.EmptyResult,
    ("tools/call", "2026-07-28"): (v2026.CallToolResult, v2026.InputRequiredResult),
    ("tools/list", "2026-07-28"): v2026.ListToolsResult,
}

EXPECTED_CLIENT_RESULTS: dict[tuple[str, str], type[BaseModel] | tuple[type[BaseModel], ...]] = {
    ("ping", "2024-11-05"): v2025.EmptyResult,
    ("roots/list", "2024-11-05"): v2025.ListRootsResult,
    ("sampling/createMessage", "2024-11-05"): v2025.CreateMessageResult,
    ("ping", "2025-03-26"): v2025.EmptyResult,
    ("roots/list", "2025-03-26"): v2025.ListRootsResult,
    ("sampling/createMessage", "2025-03-26"): v2025.CreateMessageResult,
    ("elicitation/create", "2025-06-18"): v2025.ElicitResult,
    ("ping", "2025-06-18"): v2025.EmptyResult,
    ("roots/list", "2025-06-18"): v2025.ListRootsResult,
    ("sampling/createMessage", "2025-06-18"): v2025.CreateMessageResult,
    ("elicitation/create", "2025-11-25"): v2025.ElicitResult,
    ("ping", "2025-11-25"): v2025.EmptyResult,
    ("roots/list", "2025-11-25"): v2025.ListRootsResult,
    ("sampling/createMessage", "2025-11-25"): v2025.CreateMessageResult,
}

EMPTY_SERVER_RESPONSE_METHODS = frozenset(
    {"logging/setLevel", "ping", "resources/subscribe", "resources/unsubscribe", "subscriptions/listen"}
)
EMPTY_CLIENT_RESPONSE_METHODS = frozenset({"ping"})

# Pre-2026 versions share the 2025-11-25 surface package.
PACKAGE_BY_VERSION = {
    "2024-11-05": "mcp.types.v2025_11_25",
    "2025-03-26": "mcp.types.v2025_11_25",
    "2025-06-18": "mcp.types.v2025_11_25",
    "2025-11-25": "mcp.types.v2025_11_25",
    "2026-07-28": "mcp.types.v2026_07_28",
}

# The three reserved `params._meta` entries the 2026 surface requires on every request.
META_TRIPLE: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}

# One minimal valid params mapping per surface request class.
REQUEST_PARAMS_FIXTURES: dict[type[BaseModel], dict[str, Any] | None] = {
    v2025.CallToolRequest: {"name": "echo"},
    v2025.CompleteRequest: {"ref": {"type": "ref/prompt", "name": "p"}, "argument": {"name": "a", "value": "v"}},
    v2025.CreateMessageRequest: {
        "messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}],
        "maxTokens": 100,
    },
    v2025.ElicitRequest: {"message": "m", "requestedSchema": {"type": "object", "properties": {}}},
    v2025.GetPromptRequest: {"name": "greeting"},
    v2025.InitializeRequest: {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "client", "version": "1.0"},
    },
    v2025.ListPromptsRequest: None,
    v2025.ListResourcesRequest: None,
    v2025.ListResourceTemplatesRequest: None,
    v2025.ListRootsRequest: None,
    v2025.ListToolsRequest: None,
    v2025.PingRequest: None,
    v2025.ReadResourceRequest: {"uri": "https://example.com/resource"},
    v2025.SetLevelRequest: {"level": "info"},
    v2025.SubscribeRequest: {"uri": "https://example.com/resource"},
    v2025.UnsubscribeRequest: {"uri": "https://example.com/resource"},
    v2026.CallToolRequest: {"_meta": META_TRIPLE, "name": "echo"},
    v2026.CompleteRequest: {
        "_meta": META_TRIPLE,
        "ref": {"type": "ref/prompt", "name": "p"},
        "argument": {"name": "a", "value": "v"},
    },
    v2026.DiscoverRequest: {"_meta": META_TRIPLE},
    v2026.GetPromptRequest: {"_meta": META_TRIPLE, "name": "greeting"},
    v2026.ListPromptsRequest: {"_meta": META_TRIPLE},
    v2026.ListResourcesRequest: {"_meta": META_TRIPLE},
    v2026.ListResourceTemplatesRequest: {"_meta": META_TRIPLE},
    v2026.ListToolsRequest: {"_meta": META_TRIPLE},
    v2026.ReadResourceRequest: {"_meta": META_TRIPLE, "uri": "https://example.com/resource"},
    v2026.SubscriptionsListenRequest: {"_meta": META_TRIPLE, "notifications": {}},
}

NOTIFICATION_PARAMS_FIXTURES: dict[type[BaseModel], dict[str, Any] | None] = {
    v2025.CancelledNotification: {"requestId": 1},
    v2025.ElicitationCompleteNotification: {"elicitationId": "e1"},
    v2025.InitializedNotification: None,
    v2025.LoggingMessageNotification: {"level": "info", "data": "x"},
    v2025.ProgressNotification: {"progressToken": 1, "progress": 0.5},
    v2025.PromptListChangedNotification: None,
    v2025.ResourceListChangedNotification: None,
    v2025.ResourceUpdatedNotification: {"uri": "https://example.com/resource"},
    v2025.RootsListChangedNotification: None,
    v2025.ToolListChangedNotification: None,
    v2026.CancelledNotification: {"requestId": 1},
    v2026.LoggingMessageNotification: {"level": "info", "data": "x"},
    v2026.ProgressNotification: {"progressToken": 1, "progress": 0.5},
    v2026.PromptListChangedNotification: None,
    v2026.ResourceListChangedNotification: None,
    v2026.ResourceUpdatedNotification: {"uri": "https://example.com/resource"},
    v2026.SubscriptionsAcknowledgedNotification: {"notifications": {}},
    v2026.ToolListChangedNotification: None,
}

# One minimal valid result body per response row value (class or union alias).
RESULT_BODY_FIXTURES: dict[type[BaseModel] | UnionType, dict[str, Any]] = {
    v2025.CallToolResult: {"content": []},
    v2025.CompleteResult: {"completion": {"values": []}},
    v2025.CreateMessageResult: {"role": "assistant", "content": {"type": "text", "text": "hi"}, "model": "m"},
    v2025.ElicitResult: {"action": "accept"},
    v2025.EmptyResult: {},
    v2025.GetPromptResult: {"messages": []},
    v2025.InitializeResult: {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "serverInfo": {"name": "server", "version": "1.0"},
    },
    v2025.ListPromptsResult: {"prompts": []},
    v2025.ListResourcesResult: {"resources": []},
    v2025.ListResourceTemplatesResult: {"resourceTemplates": []},
    v2025.ListRootsResult: {"roots": [{"uri": "file:///workspace"}]},
    v2025.ListToolsResult: {"tools": []},
    v2025.ReadResourceResult: {"contents": []},
    v2026.AnyCallToolResult: {"content": [], "resultType": "complete"},
    v2026.AnyGetPromptResult: {"messages": [], "resultType": "complete"},
    v2026.AnyReadResourceResult: {"contents": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private"},
    v2026.CompleteResult: {"completion": {"values": []}, "resultType": "complete"},
    v2026.DiscoverResult: {
        "supportedVersions": ["2026-07-28"],
        "capabilities": {},
        "serverInfo": {"name": "server", "version": "1.0"},
        "resultType": "complete",
        "ttlMs": 0,
        "cacheScope": "private",
    },
    v2026.EmptyResult: {"resultType": "complete"},
    v2026.ListPromptsResult: {"prompts": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private"},
    v2026.ListResourcesResult: {"resources": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private"},
    v2026.ListResourceTemplatesResult: {
        "resourceTemplates": [],
        "resultType": "complete",
        "ttlMs": 0,
        "cacheScope": "private",
    },
    v2026.ListToolsResult: {"tools": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private"},
}


def test_maps_define_exactly_the_expected_methods_for_every_known_version():
    # Derive the version axis from KNOWN_PROTOCOL_VERSIONS so a new version
    # without map rows fails here rather than gating every method at runtime.
    assert set(EXPECTED_METHODS) == set(KNOWN_PROTOCOL_VERSIONS)
    surface_maps: dict[str, Mapping[tuple[str, str], object]] = {
        "CLIENT_REQUESTS": methods.CLIENT_REQUESTS,
        "CLIENT_NOTIFICATIONS": methods.CLIENT_NOTIFICATIONS,
        "SERVER_REQUESTS": methods.SERVER_REQUESTS,
        "SERVER_NOTIFICATIONS": methods.SERVER_NOTIFICATIONS,
    }
    for version in KNOWN_PROTOCOL_VERSIONS:
        for map_name, surface_map in surface_maps.items():
            derived = {method for (method, row_version) in surface_map if row_version == version}
            assert derived == EXPECTED_METHODS[version][map_name], f"{map_name} at {version}"


def test_spec_client_method_sets_are_the_client_direction_projection_of_the_surface_maps():
    assert methods.SPEC_CLIENT_METHODS == {m for m, _ in methods.CLIENT_REQUESTS}
    assert methods.SPEC_CLIENT_NOTIFICATION_METHODS == {m for m, _ in methods.CLIENT_NOTIFICATIONS}
    # Server-direction methods stay out so a server-side custom registration routes as custom.
    assert "roots/list" not in methods.SPEC_CLIENT_METHODS
    assert "notifications/message" not in methods.SPEC_CLIENT_NOTIFICATION_METHODS


def test_elicit_result_surface_accepts_null_content_values_at_every_version_that_defines_it():
    """Monolith superset leniency: hosts may answer optional form fields with null."""
    for (method, _), surface in methods.CLIENT_RESULTS.items():
        if method != "elicitation/create":
            continue
        assert isinstance(surface, type)
        surface.model_validate({"action": "accept", "content": {"name": "x", "age": None}})
    for surface in (v2025.ElicitResult, v2026.ElicitResult):
        surface.model_validate({"action": "accept", "content": {"name": "x", "age": None}})


def test_server_capabilities_extensions_with_null_json_value_round_trips_at_2026():
    """Spec `JSONValue` includes `null`; the ts->json render dropped it from the vendored schema."""
    raw: dict[str, Any] = {"extensions": {"x": {"k": None}}}
    parsed = v2026.ServerCapabilities.model_validate(raw)
    assert parsed.model_dump(mode="json")["extensions"] == {"x": {"k": None}}


def test_elicit_request_surface_accepts_loose_property_schemas():
    """Older python-sdk emits `anyOf` for `Optional` form fields; the surface gate must let it through."""
    params = {
        "message": "m",
        "requestedSchema": {
            "type": "object",
            "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
        },
    }
    parsed = methods.parse_server_request("elicitation/create", "2025-11-25", params)
    assert isinstance(parsed, types.ElicitRequest)


def test_response_map_keys_mirror_the_request_map_keys():
    assert set(methods.SERVER_RESULTS) == set(methods.CLIENT_REQUESTS)
    assert set(methods.CLIENT_RESULTS) == set(methods.SERVER_REQUESTS)


def test_response_row_values_match_the_pinned_classes_and_unions():
    """Only the known empty-response methods may be valued by the bare `EmptyResult`."""
    assert set(EXPECTED_SERVER_RESULTS) == set(methods.SERVER_RESULTS)
    assert set(EXPECTED_CLIENT_RESULTS) == set(methods.CLIENT_RESULTS)
    pinned = [
        (methods.SERVER_RESULTS, EXPECTED_SERVER_RESULTS, EMPTY_SERVER_RESPONSE_METHODS),
        (methods.CLIENT_RESULTS, EXPECTED_CLIENT_RESULTS, EMPTY_CLIENT_RESPONSE_METHODS),
    ]
    for response_map, expected_rows, empty_methods in pinned:
        for (method, version), expected in expected_rows.items():
            actual = response_map[(method, version)]
            if isinstance(expected, tuple):
                assert get_args(actual) == expected, f"{method} at {version}"
            else:
                assert actual is expected, f"{method} at {version}"
            if method not in empty_methods:
                assert actual is not v2025.EmptyResult, f"{method} at {version}"
                assert actual is not v2026.EmptyResult, f"{method} at {version}"


def test_surface_keys_agree_with_their_classes_and_the_monolith_maps():
    """Each surface key's method matches its class's method literal, its monolith row, and its version's package."""
    request_maps: list[Mapping[tuple[str, str], type[BaseModel]]] = [
        methods.CLIENT_REQUESTS,
        methods.SERVER_REQUESTS,
    ]
    notification_maps: list[Mapping[tuple[str, str], type[BaseModel]]] = [
        methods.CLIENT_NOTIFICATIONS,
        methods.SERVER_NOTIFICATIONS,
    ]
    for surface_maps, monolith_map in (
        (request_maps, methods.MONOLITH_REQUESTS),
        (notification_maps, methods.MONOLITH_NOTIFICATIONS),
    ):
        for surface_map in surface_maps:
            for (method, version), surface_type in surface_map.items():
                assert method in monolith_map, f"{method} has no monolith row"
                assert get_args(surface_type.model_fields["method"].annotation) == (method,)
                assert get_args(monolith_map[method].model_fields["method"].annotation) == (method,)
                assert surface_type.__module__ == PACKAGE_BY_VERSION[version], f"{method} at {version}"
    for response_map in (methods.SERVER_RESULTS, methods.CLIENT_RESULTS):
        for (method, version), row in response_map.items():
            assert method in methods.MONOLITH_RESULTS, f"{method} has no monolith row"
            for arm in get_args(row) or (row,):
                assert arm.__module__ == PACKAGE_BY_VERSION[version], f"{method} at {version}"


def _assign_item(mapping: Any) -> None:
    mapping["new-key"] = None


def test_built_in_maps_are_immutable():
    map_names = [
        "CLIENT_NOTIFICATIONS",
        "CLIENT_REQUESTS",
        "CLIENT_RESULTS",
        "MONOLITH_NOTIFICATIONS",
        "MONOLITH_REQUESTS",
        "MONOLITH_RESULTS",
        "SERVER_NOTIFICATIONS",
        "SERVER_REQUESTS",
        "SERVER_RESULTS",
    ]
    for map_name in map_names:
        built_in = getattr(methods, map_name)
        assert isinstance(built_in, MappingProxyType), map_name
        with pytest.raises(TypeError):
            _assign_item(built_in)


def test_minimal_request_bodies_parse_through_every_request_row():
    for (method, version), surface_type in methods.CLIENT_REQUESTS.items():
        parsed = methods.parse_client_request(method, version, REQUEST_PARAMS_FIXTURES[surface_type])
        assert isinstance(parsed, types.Request), f"{method} at {version}"
    for (method, version), surface_type in methods.SERVER_REQUESTS.items():
        parsed = methods.parse_server_request(method, version, REQUEST_PARAMS_FIXTURES[surface_type])
        assert isinstance(parsed, types.Request), f"{method} at {version}"


def test_minimal_notification_bodies_parse_through_every_notification_row():
    for (method, version), surface_type in methods.CLIENT_NOTIFICATIONS.items():
        parsed = methods.parse_client_notification(method, version, NOTIFICATION_PARAMS_FIXTURES[surface_type])
        assert isinstance(parsed, types.Notification), f"{method} at {version}"
    for (method, version), surface_type in methods.SERVER_NOTIFICATIONS.items():
        parsed = methods.parse_server_notification(method, version, NOTIFICATION_PARAMS_FIXTURES[surface_type])
        assert isinstance(parsed, types.Notification), f"{method} at {version}"


def test_minimal_result_bodies_parse_through_every_result_row():
    for (method, version), row in methods.SERVER_RESULTS.items():
        parsed = methods.parse_server_result(method, version, RESULT_BODY_FIXTURES[row])
        assert isinstance(parsed, types.Result), f"{method} at {version}"
    for (method, version), row in methods.CLIENT_RESULTS.items():
        parsed = methods.parse_client_result(method, version, RESULT_BODY_FIXTURES[row])
        assert isinstance(parsed, types.Result), f"{method} at {version}"


def test_non_file_root_uri_passes_the_surface_step_and_rejects_at_the_monolith_step():
    """The monolith's `Root.uri` is file-scheme only; the surfaces declare a plain string."""
    non_file_roots = {"roots": [{"uri": "https://example.com/x"}]}
    # Surface step admits the body, so the two-step parse fails at the monolith step.
    pydantic.TypeAdapter(v2025.ListRootsResult).validate_python(non_file_roots)
    with pytest.raises(pydantic.ValidationError):
        methods.parse_client_result("roots/list", "2025-11-25", non_file_roots)

    # Same divergence on the 2026 path that embeds a roots response.
    retry_params = {"_meta": META_TRIPLE, "name": "echo", "inputResponses": {"r1": non_file_roots}}
    frame = {"jsonrpc": "2.0", "id": 0, "method": "tools/call", "params": retry_params}
    v2026.CallToolRequest.model_validate(frame, by_name=False)
    with pytest.raises(pydantic.ValidationError):
        methods.parse_client_request("tools/call", "2026-07-28", retry_params)

    file_roots = {"roots": [{"uri": "file:///workspace"}]}
    assert isinstance(methods.parse_client_result("roots/list", "2025-11-25", file_roots), types.ListRootsResult)
    retried = methods.parse_client_request(
        "tools/call", "2026-07-28", {"_meta": META_TRIPLE, "name": "echo", "inputResponses": {"r1": file_roots}}
    )
    assert isinstance(retried, types.CallToolRequest)


def test_absent_map_keys_raise_key_error_for_every_gate_shape():
    """Key absence is the version gate; the session layer maps it to `METHOD_NOT_FOUND`."""
    gated = [
        ("resources/subscribe", "2026-07-28"),  # removed at this version
        ("server/discover", "2025-11-25"),  # not yet at this version
        ("tasks/get", "2025-11-25"),  # never built-in
        ("sampling/createMessage", "2025-11-25"),  # wrong direction
    ]
    for method, version in gated:
        with pytest.raises(KeyError):
            methods.parse_client_request(method, version, None)
    with pytest.raises(KeyError):
        methods.parse_server_request("ping", "2026-07-28", None)


def test_unknown_version_strings_raise_value_error_on_every_parse_function():
    body_parsers = [
        methods.parse_client_request,
        methods.parse_server_request,
        methods.parse_client_notification,
        methods.parse_server_notification,
    ]
    for body_parser in body_parsers:
        with pytest.raises(ValueError) as excinfo:
            body_parser("ping", "2099-01-01", None)
        assert "2099-01-01" in str(excinfo.value)
    result_parsers = [methods.parse_server_result, methods.parse_client_result]
    for result_parser in result_parsers:
        with pytest.raises(ValueError) as excinfo:
            result_parser("ping", "2099-01-01", {})
        assert "2099-01-01" in str(excinfo.value)


def test_2026_07_28_requests_missing_a_reserved_meta_entry_reject_as_missing():
    for absent_key in META_TRIPLE:
        partial_meta = {key: value for key, value in META_TRIPLE.items() if key != absent_key}
        with pytest.raises(pydantic.ValidationError) as excinfo:
            methods.parse_client_request("tools/list", "2026-07-28", {"_meta": partial_meta})
        assert [error["loc"] for error in excinfo.value.errors() if error["type"] == "missing"] == [
            ("params", "_meta", absent_key)
        ]


def test_2026_07_28_results_require_result_type():
    with pytest.raises(pydantic.ValidationError):
        methods.parse_server_result("tools/call", "2026-07-28", {"content": []})
    with pytest.raises(pydantic.ValidationError):
        methods.parse_server_result("subscriptions/listen", "2026-07-28", {})


def test_empty_result_body_parses_at_versions_that_define_it():
    parsed = methods.parse_server_result("ping", "2025-11-25", {})
    assert isinstance(parsed, types.EmptyResult)


def test_2026_07_28_shaped_result_extras_pass_at_earlier_versions():
    """The earlier surface ignores unknown keys; the monolith preserves them on fields it declares."""
    parsed = methods.parse_server_result(
        "tools/list", "2025-11-25", {"tools": [], "resultType": "complete", "ttlMs": 5, "cacheScope": "public"}
    )
    assert isinstance(parsed, types.ListToolsResult)
    assert parsed.result_type == "complete"
    assert parsed.ttl_ms == 5
    assert parsed.cache_scope == "public"


def test_embedded_input_request_entries_without_method_reject_at_the_surface_step():
    """The monolith's embedded request classes default `method`, so only the surface step rejects this."""
    body = {"resultType": "input_required", "inputRequests": {"r1": {"params": None}}}
    monolith_row = methods.MONOLITH_RESULTS["tools/call"]
    monolith_only: types.Result = pydantic.TypeAdapter[Any](monolith_row).validate_python(body)
    assert isinstance(monolith_only, types.InputRequiredResult)
    with pytest.raises(pydantic.ValidationError):
        methods.parse_server_result("tools/call", "2026-07-28", body)


def test_input_required_url_elicit_without_elicitation_id_parses_at_2026():
    """A 2026-07-28 `InputRequiredResult` embedding a URL-mode elicitation parses
    through both the surface and monolith steps without `elicitationId`.

    Spec-mandated: the field is required at 2025-11-25 only and removed at
    2026-07-28; the monolith model carries it as optional so the superset can
    accept both versions.
    """
    body = {
        "resultType": "input_required",
        "inputRequests": {
            "r1": {
                "method": "elicitation/create",
                "params": {"mode": "url", "message": "Please sign in", "url": "https://example.com/auth"},
            }
        },
    }
    parsed = methods.parse_server_result("tools/call", "2026-07-28", body)
    assert isinstance(parsed, types.InputRequiredResult)
    assert parsed.input_requests is not None
    request = parsed.input_requests["r1"]
    assert isinstance(request, types.ElicitRequest)
    assert isinstance(request.params, types.ElicitRequestURLParams)
    assert request.params.url == "https://example.com/auth"
    assert request.params.elicitation_id is None


def test_none_params_omit_the_key_so_required_params_reject():
    with pytest.raises(pydantic.ValidationError) as excinfo:
        methods.parse_client_request("tools/call", "2025-11-25", None)
    assert [error["loc"] for error in excinfo.value.errors() if error["type"] == "missing"] == [("params",)]
    assert isinstance(methods.parse_client_request("ping", "2025-11-25", None), types.PingRequest)


def test_snake_case_spellings_of_required_aliased_fields_reject_as_missing():
    """Wire parsing is alias-only (`by_name=False`), at both the surface and monolith steps."""
    snake_params = {"messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}], "max_tokens": 100}
    with pytest.raises(pydantic.ValidationError) as excinfo:
        methods.parse_server_request("sampling/createMessage", "2025-11-25", snake_params)
    assert [error["loc"] for error in excinfo.value.errors() if error["type"] == "missing"] == [("params", "maxTokens")]
    with pytest.raises(pydantic.ValidationError):
        types.CreateMessageRequest.model_validate(
            {"method": "sampling/createMessage", "params": snake_params}, by_name=False
        )


def test_extension_map_rows_parse_through_the_same_functions():
    extended_surface = {**methods.CLIENT_REQUESTS, ("tasks/get", "2025-11-25"): v2025.GetTaskRequest}
    extended_monolith = {**methods.MONOLITH_REQUESTS, "tasks/get": types.GetTaskRequest}
    parsed = methods.parse_client_request(
        "tasks/get", "2025-11-25", {"taskId": "t1"}, surface=extended_surface, monolith=extended_monolith
    )
    assert isinstance(parsed, types.GetTaskRequest)
    assert parsed.params.task_id == "t1"


def test_inconsistent_extension_maps_raise_runtime_error_after_the_surface_hit():
    """Must not raise `KeyError`: the session layer treats that as the version gate."""
    extended_surface = {**methods.CLIENT_REQUESTS, ("tasks/get", "2025-11-25"): v2025.GetTaskRequest}
    with pytest.raises(RuntimeError, match="inconsistent extension maps"):
        methods.parse_client_request("tasks/get", "2025-11-25", {"taskId": "t1"}, surface=extended_surface)


def test_input_required_unions_discriminate_identically_in_both_arm_orders():
    complete_bodies: dict[str, dict[str, Any]] = {
        "tools/call": {"content": []},
        "prompts/get": {"messages": []},
        "resources/read": {"contents": []},
    }
    shared_bodies: list[dict[str, Any]] = [
        {"resultType": "input_required", "inputRequests": {"r1": {"method": "roots/list"}}},
        {"resultType": "input_required", "requestState": "blob"},
    ]
    for method, complete_body in complete_bodies.items():
        row = methods.MONOLITH_RESULTS[method]
        complete_arm, input_required_arm = get_args(row)
        assert input_required_arm is types.InputRequiredResult
        bodies: list[dict[str, Any]] = [
            complete_body,
            {**complete_body, "resultType": "complete"},
            *shared_bodies,
            {**complete_body, "resultType": "task"},  # open tag is preserved
            {**complete_body, "resultType": "input_required"},  # complete shape plus the tag
        ]
        for body in bodies:
            forward = pydantic.TypeAdapter[Any](complete_arm | input_required_arm).validate_python(body)
            reversed_order = pydantic.TypeAdapter[Any](input_required_arm | complete_arm).validate_python(body)
            assert type(forward) is type(reversed_order), f"{method}: {body}"
            assert forward.result_type == reversed_order.result_type
        through_row = pydantic.TypeAdapter[Any](row).validate_python(complete_body)
        assert isinstance(through_row, complete_arm)
        open_tagged = pydantic.TypeAdapter[Any](row).validate_python({**complete_body, "resultType": "task"})
        assert open_tagged.result_type == "task"


def test_sampling_union_keeps_the_complete_arm_first_because_order_is_load_bearing():
    """A single-block body satisfies both arms; smart-union ties resolve leftmost."""
    assert get_args(methods.MONOLITH_RESULTS["sampling/createMessage"]) == (
        types.CreateMessageResult,
        types.CreateMessageResultWithTools,
    )
    single_block: dict[str, Any] = {"role": "assistant", "content": {"type": "text", "text": "hi"}, "model": "m"}
    through_row = methods.parse_client_result("sampling/createMessage", "2025-11-25", single_block)
    assert type(through_row) is types.CreateMessageResult
    reversed_union = pydantic.TypeAdapter[Any](types.CreateMessageResultWithTools | types.CreateMessageResult)
    assert type(reversed_union.validate_python(single_block)) is types.CreateMessageResultWithTools

    array_body: dict[str, Any] = {"role": "assistant", "content": [{"type": "text", "text": "hi"}], "model": "m"}
    tool_use_body: dict[str, Any] = {
        "role": "assistant",
        "content": {"type": "tool_use", "name": "t", "id": "c1", "input": {}},
        "model": "m",
    }
    for body in (array_body, tool_use_body):
        parsed = methods.parse_client_result("sampling/createMessage", "2025-11-25", body)
        assert type(parsed) is types.CreateMessageResultWithTools


def test_validate_functions_accept_reject_and_gate_like_their_parse_siblings():
    methods.validate_client_request("tools/call", "2025-11-25", {"name": "echo"})
    methods.validate_client_notification("notifications/cancelled", "2025-11-25", {"requestId": 1})
    methods.validate_server_result("tools/list", "2025-11-25", {"tools": []})
    methods.validate_client_result("roots/list", "2025-11-25", {"roots": []})
    with pytest.raises(KeyError):
        methods.validate_client_request("custom/greet", "2025-11-25", None)
    with pytest.raises(KeyError):
        methods.validate_client_notification("custom/ping", "2025-11-25", None)
    with pytest.raises(KeyError):
        methods.validate_server_result("custom/greet", "2025-11-25", {})
    with pytest.raises(KeyError):
        methods.validate_client_result("roots/list", "2026-07-28", {})
    with pytest.raises(pydantic.ValidationError):
        methods.validate_client_request("tools/call", "2025-11-25", None)
    with pytest.raises(pydantic.ValidationError):
        methods.validate_client_notification("notifications/progress", "2025-11-25", {"progressToken": []})
    with pytest.raises(pydantic.ValidationError):
        methods.validate_server_result("tools/list", "2025-11-25", {"tools": 42})
    with pytest.raises(pydantic.ValidationError):
        methods.validate_client_result("roots/list", "2025-11-25", {"roots": 42})
    with pytest.raises(ValueError):
        methods.validate_client_request("ping", "2099-01-01", None)


# One minimal monolith result instance per request method, dumped via the same
# `_dump_result` path the runner uses. Cacheable results set `ttl_ms`/`cache_scope`
# explicitly because the monolith no longer defaults them and 2026 requires them.
MONOLITH_RESULT_FIXTURES: dict[str, types.Result] = {
    "completion/complete": types.CompleteResult(completion=types.Completion(values=[])),
    "initialize": types.InitializeResult(
        protocol_version="2025-11-25",
        capabilities=types.ServerCapabilities(),
        server_info=types.Implementation(name="server", version="1.0"),
    ),
    "logging/setLevel": types.EmptyResult(),
    "ping": types.EmptyResult(),
    "prompts/get": types.GetPromptResult(messages=[]),
    "prompts/list": types.ListPromptsResult(prompts=[], ttl_ms=0, cache_scope="private"),
    "resources/list": types.ListResourcesResult(resources=[], ttl_ms=0, cache_scope="private"),
    "resources/read": types.ReadResourceResult(contents=[], ttl_ms=0, cache_scope="private"),
    "resources/subscribe": types.EmptyResult(),
    "resources/templates/list": types.ListResourceTemplatesResult(
        resource_templates=[], ttl_ms=0, cache_scope="private"
    ),
    "resources/unsubscribe": types.EmptyResult(),
    "server/discover": types.DiscoverResult(
        supported_versions=["2026-07-28"],
        capabilities=types.ServerCapabilities(),
        server_info=types.Implementation(name="server", version="1.0"),
        ttl_ms=0,
        cache_scope="private",
    ),
    "subscriptions/listen": types.EmptyResult(result_type="complete"),
    "tools/call": types.CallToolResult(content=[]),
    "tools/list": types.ListToolsResult(tools=[], ttl_ms=0, cache_scope="private"),
}

CACHEABLE_METHODS = frozenset(m for m, r in MONOLITH_RESULT_FIXTURES.items() if isinstance(r, types.CacheableResult))


@pytest.mark.parametrize(("method", "version"), sorted(methods.SERVER_RESULTS))
def test_dumped_monolith_results_round_trip_through_serialize_server_result(method: str, version: str):
    """The outbound sieve must accept every correctly-typed handler return and re-validate."""
    instance = MONOLITH_RESULT_FIXTURES[method]
    dumped = instance.model_dump(by_alias=True, mode="json", exclude_none=True)
    sieved = methods.serialize_server_result(method, version, dumped)
    methods.validate_server_result(method, version, sieved)


PRE_2026 = [v for v in KNOWN_PROTOCOL_VERSIONS if v < "2026-07-28"]


@pytest.mark.parametrize(("method", "version"), [k for k in sorted(methods.SERVER_RESULTS) if k[1] in PRE_2026])
def test_serialize_server_result_drops_2026_only_keys_at_pre_2026_versions(method: str, version: str):
    instance = MONOLITH_RESULT_FIXTURES[method]
    dumped = instance.model_dump(by_alias=True, mode="json", exclude_none=True)
    sieved = methods.serialize_server_result(method, version, dumped)
    if getattr(instance, "result_type", None) is not None:
        assert "resultType" in dumped
    assert "resultType" not in sieved
    if method in CACHEABLE_METHODS:
        assert "ttlMs" in dumped and "cacheScope" in dumped
    assert "ttlMs" not in sieved
    assert "cacheScope" not in sieved


def test_serialize_server_result_keeps_2026_only_keys_at_2026_07_28():
    dumped = MONOLITH_RESULT_FIXTURES["tools/list"].model_dump(by_alias=True, mode="json", exclude_none=True)
    sieved = methods.serialize_server_result("tools/list", "2026-07-28", dumped)
    assert sieved["resultType"] == "complete"
    assert sieved["ttlMs"] == 0
    assert sieved["cacheScope"] == "private"


@pytest.mark.parametrize("version", KNOWN_PROTOCOL_VERSIONS)
def test_serialize_server_result_preserves_arbitrary_meta_value_identically(version: str):
    meta = {"custom-key": 1, "modelcontextprotocol.io/foo": "bar"}
    dumped: dict[str, Any] = {"tools": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private", "_meta": meta}
    sieved = methods.serialize_server_result("tools/list", version, dumped)
    assert sieved["_meta"] == meta


def test_serialize_server_result_preserves_open_type_extras():
    """`inputSchema` and nested `_meta` are open key-value bags; the sieve must not strip them."""
    input_schema = {"type": "object", "title": "X", "additionalProperties": False, "$defs": {"Y": {"type": "string"}}}
    nested_meta = {"com.example/tag": "v"}
    tool = {"name": "echo", "inputSchema": input_schema, "_meta": nested_meta}
    sieved = methods.serialize_server_result("tools/list", "2025-11-25", {"tools": [tool]})
    assert sieved["tools"][0]["inputSchema"] == input_schema
    assert sieved["tools"][0]["_meta"] == nested_meta


def test_serialize_server_result_drops_an_unknown_nested_tool_field():
    tool = {"name": "echo", "inputSchema": {"type": "object"}, "unknownField": 1}
    sieved = methods.serialize_server_result("tools/list", "2025-11-25", {"tools": [tool], "resultType": "complete"})
    assert sieved == {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}


def test_serialize_server_result_raises_key_error_for_an_absent_row_and_value_error_for_an_unknown_version():
    with pytest.raises(KeyError):
        methods.serialize_server_result("server/discover", "2025-11-25", {})
    with pytest.raises(ValueError):
        methods.serialize_server_result("ping", "2099-01-01", {})


def test_importing_the_module_builds_no_adapters_and_identical_rows_share_one():
    # Execute a fresh copy so the cache assertion is order-independent.
    spec = importlib.util.find_spec("mcp.types.methods")
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh._adapter.cache_info().currsize == 0
    fresh.parse_server_result("ping", "2025-11-25", {})
    assert fresh._adapter.cache_info().currsize == 2
    # Identical row values at another version: no new adapters.
    fresh.parse_server_result("ping", "2024-11-05", {})
    assert fresh._adapter.cache_info().currsize == 2
