"""Inbound facts of `mcp.types.wire.parse_as`: the version-keyed mandates and
the retention/leniency behavior around them.

Parsing is one lenient superset parse at every version; the only version-keyed
rejections are the three 2026-07-28 mandates, surfaced as pydantic validation
errors with pinned error types (`result_type_invalid`, `missing_required_meta`,
and plain `missing` for embedded input-request entries without a method).
"""

from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    AudioContent,
    CallToolRequest,
    CallToolResult,
    ClientNotification,
    ClientRequest,
    ClientResult,
    ContentBlock,
    CreateMessageResult,
    CreateMessageResultWithTools,
    DiscoverResult,
    ElicitRequest,
    EmptyResult,
    InitializeRequest,
    InputRequiredResult,
    ListRootsRequest,
    ListToolsRequest,
    ListToolsResult,
    ProgressNotification,
    ServerResult,
    SubscriptionsListenRequest,
    TaskMetadata,
    ToolUseContent,
    client_result_adapter,
    server_result_adapter,
)
from mcp.types.wire import parse_as

ALL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")
EARLIER_VERSIONS = ALL_VERSIONS[:-1]

FULL_META: dict[str, Any] = {
    PROTOCOL_VERSION_META_KEY: "2026-07-28",
    CLIENT_INFO_META_KEY: {"name": "example-client", "version": "1.0.0"},
    CLIENT_CAPABILITIES_META_KEY: {},
}

TEXT_BLOCK = {"type": "text", "text": "hi"}


# resultType mandate (spec-mandated: 2026-07-28 rejects a present-and-
# unrecognized resultType; absence is equivalent to "complete") ---------------


def test_absent_result_type_accepted_on_2026_07_28() -> None:
    """Absence means "complete"; the parsed field stays None, never materialized."""
    result = parse_as(ServerResult, {"content": [TEXT_BLOCK]}, "2026-07-28")
    assert isinstance(result, CallToolResult)
    assert result.result_type is None


def test_recognized_result_type_retained_on_2026_07_28() -> None:
    result = parse_as(ServerResult, {"content": [TEXT_BLOCK], "resultType": "complete"}, "2026-07-28")
    assert isinstance(result, CallToolResult)
    assert result.result_type == "complete"


def test_unrecognized_result_type_rejected_on_2026_07_28() -> None:
    """2026-07-28 recognizes "complete" and "input_required" only; other values are
    rejected at request level with the pinned error type."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, {"content": [], "resultType": "task"}, "2026-07-28")
    (error,) = exc_info.value.errors()
    assert error["type"] == "result_type_invalid"
    assert error["loc"] == ("resultType",)


def test_unrecognized_result_type_rejected_for_concrete_type_too() -> None:
    """The mandate applies to any parsed result, union-routed or concrete."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult, {"content": [], "resultType": "task"}, "2026-07-28")
    assert exc_info.value.errors()[0]["type"] == "result_type_invalid"


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_any_result_type_accepted_on_earlier_versions(version: str) -> None:
    """Before 2026-07-28 there is no resultType mandate: any value parses and is
    retained (strictly-more-lenient inbound behavior)."""
    result = parse_as(ServerResult, {"content": [], "resultType": "anything-at-all"}, version)
    assert isinstance(result, CallToolResult)
    assert result.result_type == "anything-at-all"


# Caching fields (spec-mandated: optional on parse, retained at every version)


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_caching_fields_retained_on_parse_at_every_version(version: str) -> None:
    result = parse_as(ServerResult, {"tools": [], "ttlMs": 9, "cacheScope": "public"}, version)
    assert isinstance(result, ListToolsResult)
    assert result.ttl_ms == 9
    assert result.cache_scope == "public"


# Result-union routing (spec-mandated: 2026-07-28 response bodies discriminate
# complete vs input-required by resultType) -----------------------------------


def test_input_required_body_routes_by_result_type_on_2026_07_28() -> None:
    result = parse_as(ServerResult, {"resultType": "input_required"}, "2026-07-28")
    assert isinstance(result, InputRequiredResult)


def test_input_required_body_with_state_routes_by_result_type() -> None:
    result = parse_as(ServerResult, {"resultType": "input_required", "requestState": "s"}, "2026-07-28")
    assert isinstance(result, InputRequiredResult)
    assert result.request_state == "s"


def test_complete_body_parses_as_call_tool_result_on_2026_07_28() -> None:
    result = parse_as(ServerResult, {"content": [TEXT_BLOCK], "resultType": "complete"}, "2026-07-28")
    assert isinstance(result, CallToolResult)


def test_result_type_route_inactive_for_concrete_type() -> None:
    """A concrete parse target is honored as given: an input-required-tagged body
    offered to CallToolResult validates on CallToolResult's own terms."""
    result = parse_as(CallToolResult, {"resultType": "input_required", "content": []}, "2026-07-28")
    assert isinstance(result, CallToolResult)


def test_result_type_route_inactive_on_earlier_versions() -> None:
    """Before 2026-07-28 no resultType routing exists; the value is retained on the
    open-shaped empty-result arm."""
    result = parse_as(ServerResult, {"resultType": "input_required"}, "2025-11-25")
    assert isinstance(result, EmptyResult)
    assert result.result_type == "input_required"


# Identical-key-set sibling arms (SDK-defined: the monolith splits the schema's
# single sampling result into a single-content arm and an array-content arm
# with the same top-level keys; routing tries every structurally matching arm,
# best match first, so a body its best-looking arm rejects still parses when a
# sibling accepts it) -----------------------------------------------------------


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_sampling_with_tools_body_parses_as_the_array_content_arm(version: str) -> None:
    """A sampling response whose content is an array with a tool-use block (legal
    wire shape since 2025-11-25) is rejected by the single-content arm and must
    fall through to the array-content arm; inbound membership is never
    version-gated."""
    body: dict[str, Any] = {
        "role": "assistant",
        "content": [TEXT_BLOCK, {"type": "tool_use", "id": "call-1", "name": "get_weather", "input": {}}],
        "model": "example-model",
    }
    result = parse_as(ClientResult, body, version)
    assert isinstance(result, CreateMessageResultWithTools)
    assert isinstance(result.content, list)
    assert result.content[1] == ToolUseContent(id="call-1", name="get_weather", input={})


def test_single_content_sampling_body_parses_as_the_single_content_arm() -> None:
    """A single non-tool content block satisfies both sampling arms; the
    first-declared (single-content) arm wins, so plain sampling responses keep
    resolving exactly as they did before the array-content arm existed."""
    body = {"role": "assistant", "content": TEXT_BLOCK, "model": "example-model"}
    result = parse_as(ClientResult, body, "2025-11-25")
    assert isinstance(result, CreateMessageResult)


def test_result_body_rejected_with_the_best_matching_arms_errors_when_no_arm_validates() -> None:
    """A body keyed like a discover result but missing required supportedVersions
    matches several arms structurally and validates as none of them; the reject
    surfaces the best-matching arm's own errors."""
    body: dict[str, Any] = {
        "capabilities": {},
        "serverInfo": {"name": "s", "version": "1"},
        "ttlMs": 1000,
        "cacheScope": "public",
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, body, "2026-07-28")
    (error,) = exc_info.value.errors()
    assert error["type"] == "missing"
    assert error["loc"] == ("supportedVersions",)


RESULT_UNION_ADAPTERS: tuple[tuple[Any, TypeAdapter[Any]], ...] = (
    (ClientResult, client_result_adapter),
    (ServerResult, server_result_adapter),
)


def _wire_key_tie_groups(union: Any) -> set[tuple[type[Any], ...]]:
    """The arms of `union` with identical top-level wire-key sets, grouped
    (groups of two or more, arms in declaration order)."""
    by_keys: dict[frozenset[str], list[type[Any]]] = {}
    for arm in get_args(union):
        keys = frozenset(field.serialization_alias or field.alias or name for name, field in arm.model_fields.items())
        by_keys.setdefault(keys, []).append(arm)
    return {tuple(arms) for arms in by_keys.values() if len(arms) > 1}


# Tied arms cannot be ranked apart by key counting, so each group below carries
# bodies pinning that candidate trial resolves the same class the plain smart
# union picks: one body both arms validate (tie, first-declared wins), and
# bodies only the later-declared arm validates (the trial must fall through).
TIED_ARM_EQUIVALENCE_BODIES: dict[tuple[type[Any], ...], tuple[tuple[str, dict[str, Any]], ...]] = {
    (CreateMessageResult, CreateMessageResultWithTools): (
        ("single-content", {"role": "assistant", "content": TEXT_BLOCK, "model": "example-model"}),
        (
            "tool-use-content",
            {
                "role": "assistant",
                "content": [TEXT_BLOCK, {"type": "tool_use", "id": "call-1", "name": "get_weather", "input": {}}],
                "model": "example-model",
            },
        ),
        ("text-array-content", {"role": "assistant", "content": [TEXT_BLOCK], "model": "example-model"}),
    ),
}


def test_every_tied_arm_group_in_a_public_result_union_has_equivalence_bodies() -> None:
    """SDK-defined completeness pin: the tie groups derived from the public result
    unions are exactly the groups carrying equivalence bodies above, so an arm
    added later with an existing arm's key set fails here until its bodies are
    added."""
    derived = {group for union, _ in RESULT_UNION_ADAPTERS for group in _wire_key_tie_groups(union)}
    assert derived == set(TIED_ARM_EQUIVALENCE_BODIES)


@pytest.mark.parametrize("version", ALL_VERSIONS)
@pytest.mark.parametrize(
    ("union", "adapter", "body"),
    [
        (union, adapter, body)
        for union, adapter in RESULT_UNION_ADAPTERS
        for group, bodies in TIED_ARM_EQUIVALENCE_BODIES.items()
        if set(group) <= set(get_args(union))
        for _, body in bodies
    ],
    ids=[
        label
        for union, _ in RESULT_UNION_ADAPTERS
        for group, bodies in TIED_ARM_EQUIVALENCE_BODIES.items()
        if set(group) <= set(get_args(union))
        for label, _ in bodies
    ],
)
def test_tied_arm_bodies_resolve_to_the_same_class_as_the_plain_union_adapter(
    union: Any, adapter: TypeAdapter[Any], body: dict[str, Any], version: str
) -> None:
    """SDK-defined equivalence pin: for bodies aimed at identical-key-set sibling
    arms, `parse_as` resolves the member class the plain smart union picks at
    every version — the routing step never rejects or re-routes a body the raw
    adapter accepts."""
    assert type(parse_as(union, body, version)) is type(adapter.validate_python(body))


# Required request _meta mandate (spec-mandated: 2026-07-28 requests carry all
# three reserved keys; each key is independently required) --------------------


def test_missing_meta_triple_rejected_on_2026_07_28() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ClientRequest, {"method": "tools/list"}, "2026-07-28")
    errors = exc_info.value.errors()
    assert [error["type"] for error in errors] == ["missing_required_meta"] * 3
    assert [error["loc"] for error in errors] == [
        ("params", "_meta", PROTOCOL_VERSION_META_KEY),
        ("params", "_meta", CLIENT_INFO_META_KEY),
        ("params", "_meta", CLIENT_CAPABILITIES_META_KEY),
    ]


def test_partial_meta_triple_reports_each_missing_key() -> None:
    partial = {key: value for key, value in FULL_META.items() if key != CLIENT_CAPABILITIES_META_KEY}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ClientRequest, {"method": "tools/list", "params": {"_meta": partial}}, "2026-07-28")
    (error,) = exc_info.value.errors()
    assert error["type"] == "missing_required_meta"
    assert error["loc"] == ("params", "_meta", CLIENT_CAPABILITIES_META_KEY)


def test_full_meta_triple_parses_and_coexists_with_progress_token() -> None:
    """The reserved keys share the _meta object with the pre-existing progress
    token slot (whose wire name lands in the typed snake_case slot)."""
    meta = {**FULL_META, "progressToken": 7}
    request = parse_as(ClientRequest, {"method": "tools/list", "params": {"_meta": meta}}, "2026-07-28")
    assert isinstance(request, ListToolsRequest)
    assert request.params is not None and request.params.meta is not None
    assert request.params.meta.get("progress_token") == 7
    assert request.params.meta[CLIENT_INFO_META_KEY] == FULL_META[CLIENT_INFO_META_KEY]


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_meta_triple_not_required_on_earlier_versions(version: str) -> None:
    """Before 2026-07-28 a bare request is complete as-is."""
    request = parse_as(ClientRequest, {"method": "tools/list"}, version)
    assert isinstance(request, ListToolsRequest)


def test_meta_triple_not_required_for_notifications() -> None:
    """The reserved-keys requirement applies to requests; notifications parse
    without _meta on 2026-07-28."""
    payload = {"method": "notifications/progress", "params": {"progressToken": 1, "progress": 0.5}}
    notification = parse_as(ClientNotification, payload, "2026-07-28")
    assert isinstance(notification, ProgressNotification)


def test_unknown_meta_keys_retained_on_parse() -> None:
    """Unknown _meta keys are retained verbatim at every version (open map)."""
    meta = {**FULL_META, "example.com/trace": "abc"}
    request = parse_as(ClientRequest, {"method": "tools/list", "params": {"_meta": meta}}, "2026-07-28")
    assert isinstance(request, ListToolsRequest)
    assert request.params is not None and request.params.meta is not None
    assert request.params.meta["example.com/trace"] == "abc"


# Content-block membership (spec-mandated: one superset membership at every
# version, inbound lenient; an unknown type tag is rejected at every version
# because all deployed peers treat the union as closed) ------------------------


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_newer_content_blocks_parse_at_every_version(version: str) -> None:
    """audio content (added 2025-03-26) parses even under 2024-11-05: inbound
    membership is never version-gated."""
    result = parse_as(
        CallToolResult, {"content": [{"type": "audio", "data": "UklGRg==", "mimeType": "audio/wav"}]}, version
    )
    assert isinstance(result.content[0], AudioContent)


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_unknown_content_tag_rejected_at_every_version(version: str) -> None:
    result = pytest.raises(ValidationError, parse_as, CallToolResult, {"content": [{"type": "bogus"}]}, version)
    (error,) = result.value.errors()
    assert error["type"] == "union_tag_invalid"
    assert error["loc"] == ("content", 0)


def test_unknown_content_tag_rejected_inside_a_routed_result() -> None:
    """The unknown-tag refinement is location-based: it also fires when the
    failing block sits inside a result the union routing selected."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, {"content": [{"type": "bogus", "text": "x"}]}, "2025-11-25")
    (error,) = exc_info.value.errors()
    assert error["type"] == "union_tag_invalid"
    assert error["loc"] == ("content", 0)


def test_unknown_tag_at_the_top_of_a_union_parse() -> None:
    """A bare content block offered to the union directly reports the unknown tag
    at the payload root."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ContentBlock, {"type": "bogus", "text": "x"}, "2025-11-25")
    (error,) = exc_info.value.errors()
    assert error["type"] == "union_tag_invalid"
    assert error["loc"] == ()


def test_known_tag_with_invalid_fields_is_a_structural_failure() -> None:
    """A recognized tag whose block fails validation elsewhere surfaces the
    original field errors — the tag is known, so the failure is structural,
    not an unknown union member."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult, {"content": [{"type": "text", "text": 5}]}, "2025-11-25")
    error_types = {error["type"] for error in exc_info.value.errors()}
    assert "union_tag_invalid" not in error_types
    assert "string_type" in error_types


def test_non_string_tag_is_a_structural_failure() -> None:
    """Only a string tag can name a union member; anything else surfaces the
    plain validation error."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult, {"content": [{"type": 5}]}, "2025-11-25")
    assert all(error["type"] != "union_tag_invalid" for error in exc_info.value.errors())


def test_unknown_tag_reported_when_mixed_with_structural_failures() -> None:
    """A payload can be wrong in several places at once; the unknown tag is the
    reported failure so multi-defect payloads classify deterministically."""
    payload = {"content": [{"type": "bogus"}, {"type": "text", "text": 5}]}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult, payload, "2025-11-25")
    (error,) = exc_info.value.errors()
    assert error["type"] == "union_tag_invalid"
    assert error["loc"] == ("content", 0)


# Embedded input requests (spec-mandated: 2026-07-28 inputRequests map values
# are full request payloads, method required) ----------------------------------


def test_input_request_entries_parse_to_their_request_types() -> None:
    payload = {
        "resultType": "input_required",
        "inputRequests": {
            "roots": {"method": "roots/list"},
            "consent": {
                "method": "elicitation/create",
                "params": {"message": "ok?", "requestedSchema": {"type": "object"}},
            },
        },
    }
    result = parse_as(ServerResult, payload, "2026-07-28")
    assert isinstance(result, InputRequiredResult)
    assert result.input_requests is not None
    assert isinstance(result.input_requests["consent"], ElicitRequest)


def test_input_request_entry_without_method_is_rejected_at_its_own_location() -> None:
    """Map values are full request payloads, so an entry that supplied no method
    fails at the entry's own method key — a structural `missing` failure, which
    classifies as invalid params, not as an unknown union member."""
    payload = {"resultType": "input_required", "inputRequests": {"q1": {"message": "hi"}}}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, payload, "2026-07-28")
    (error,) = exc_info.value.errors()
    assert error["type"] == "missing"
    assert error["loc"] == ("inputRequests", "q1", "method")


def test_only_the_method_less_input_request_entries_report_missing_method() -> None:
    """The method mandate walks every entry: entries that supplied their method
    pass, and each entry that did not gets its own `missing` line error."""
    payload: dict[str, Any] = {
        "resultType": "input_required",
        "inputRequests": {
            "roots": {"method": "roots/list"},
            "q1": {"params": {}},
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, payload, "2026-07-28")
    (error,) = exc_info.value.errors()
    assert error["type"] == "missing"
    assert error["loc"] == ("inputRequests", "q1", "method")


def test_method_less_input_request_entry_accepted_on_raw_validate() -> None:
    """SDK-defined leniency: the map is a plain union alias and the request
    models default their method literals, so raw validation (no version in
    play) accepts a method-less entry as the all-optional member."""
    result = InputRequiredResult.model_validate({"inputRequests": {"k1": {"params": {}}}})
    assert result.input_requests is not None
    entry = result.input_requests["k1"]
    assert isinstance(entry, ListRootsRequest)
    assert "method" not in entry.model_fields_set


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_method_less_input_request_entry_accepted_below_2026_07_28(version: str) -> None:
    """The method mandate is 2026-07-28's, not earlier versions': below the
    version that defines the map, inbound parsing stays lenient."""
    result = parse_as(InputRequiredResult, {"inputRequests": {"k1": {"params": {}}}}, version)
    assert result.input_requests is not None
    assert isinstance(result.input_requests["k1"], ListRootsRequest)


def test_method_less_input_request_entry_accepted_at_unknown_version() -> None:
    """Unknown version strings parse with no version-keyed mandates applied,
    so the method mandate does not fire either."""
    result = parse_as(InputRequiredResult, {"inputRequests": {"k1": {"params": {}}}}, "2099-01-01")
    assert result.input_requests is not None
    assert isinstance(result.input_requests["k1"], ListRootsRequest)


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_unknown_method_input_request_entry_rejects_structurally(version: str) -> None:
    """An entry whose method value names no member fails the plain union
    structurally (`literal_error`/`missing` line errors, classifying as
    invalid params) at every version — never as an unknown union member,
    which is reserved for content-block type tags."""
    payload: dict[str, Any] = {"inputRequests": {"k1": {"method": "bogus/method", "params": {}}}}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(InputRequiredResult, payload, version)
    error_types = {error["type"] for error in exc_info.value.errors()}
    assert error_types <= {"literal_error", "missing"}


def test_unknown_method_input_request_entry_rejects_on_raw_validate() -> None:
    """The unknown-method rejection is the plain union's own, so it fires on
    raw validation too, with the same structural error surface."""
    with pytest.raises(ValidationError) as exc_info:
        InputRequiredResult.model_validate({"inputRequests": {"k1": {"method": "bogus/method", "params": {}}}})
    error_types = {error["type"] for error in exc_info.value.errors()}
    assert error_types <= {"literal_error", "missing"}


# Discover results (spec-mandated: supportedVersions is required) --------------


def test_discover_result_without_supported_versions_is_rejected() -> None:
    payload: dict[str, Any] = {"capabilities": {}, "serverInfo": {"name": "s", "version": "1"}}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(DiscoverResult, payload, "2026-07-28")
    assert exc_info.value.errors()[0]["type"] == "missing"
    assert exc_info.value.errors()[0]["loc"] == ("supportedVersions",)


def test_complete_discover_result_parses() -> None:
    payload: dict[str, Any] = {
        "supportedVersions": ["2026-07-28", "2025-11-25"],
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "s", "version": "1"},
    }
    result = parse_as(ServerResult, payload, "2026-07-28")
    assert isinstance(result, DiscoverResult)
    assert result.supported_versions == ["2026-07-28", "2025-11-25"]


# Global inbound leniency (deployed-peer-mandated: every inbound-strictness
# interop incident on record was caused by rejecting unknown data) -------------


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_unknown_fields_ignored_at_every_version(version: str) -> None:
    payload = {
        "method": "tools/list",
        "params": {"cursor": "c", "futureField": 1, "_meta": FULL_META},
        "futureField": 2,
    }
    request = parse_as(ClientRequest, payload, version)
    assert isinstance(request, ListToolsRequest)


def test_unknown_capability_keys_accepted() -> None:
    payload = {
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {"futureCapability": {"x": 1}},
            "clientInfo": {"name": "c", "version": "1"},
        },
    }
    request = parse_as(ClientRequest, payload, "2025-03-26")
    assert isinstance(request, InitializeRequest)


def test_future_protocol_version_value_accepted_on_parse() -> None:
    """protocolVersion is a plain string field; whether a version is acceptable
    is negotiation logic, not parsing."""
    payload = {
        "method": "initialize",
        "params": {
            "protocolVersion": "3025-01-01",
            "capabilities": {},
            "clientInfo": {"name": "c", "version": "1"},
        },
    }
    request = parse_as(ClientRequest, payload, "2025-03-26")
    assert isinstance(request, InitializeRequest)
    assert request.params.protocol_version == "3025-01-01"


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_task_metadata_surfaced_on_parse_at_every_version(version: str) -> None:
    """The 2025-11-25 task field is typed and surfaced wherever it arrives;
    inbound parsing never strips it."""
    payload = {"method": "tools/call", "params": {"name": "t", "task": {"ttl": 5000}, "_meta": FULL_META}}
    request = parse_as(ClientRequest, payload, version)
    assert isinstance(request, CallToolRequest)
    assert request.params.task == TaskMetadata(ttl=5000)


def test_subscription_filter_extension_keys_retained_on_parse() -> None:
    """Extensions merge additional keys into the filter object; they round-trip
    instead of being ignored."""
    payload = {
        "method": "subscriptions/listen",
        "params": {"notifications": {"toolsListChanged": True, "taskIds": ["t1"]}, "_meta": FULL_META},
    }
    request = parse_as(ClientRequest, payload, "2026-07-28")
    assert isinstance(request, SubscriptionsListenRequest)
    dumped = request.params.notifications.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"toolsListChanged": True, "taskIds": ["t1"]}


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_scalar_structured_content_accepted_at_every_version(version: str) -> None:
    """2026-07-28 opened structuredContent to any JSON value; earlier versions
    retain whatever arrives (never narrowed on parse)."""
    result = parse_as(ServerResult, {"content": [], "structuredContent": 5}, version)
    assert isinstance(result, CallToolResult)
    assert result.structured_content == 5


# Unknown negotiated versions (one stance per direction: parsing is lenient —
# an unknown version is most plausibly newer than the SDK, and its mandates
# cannot be known) --------------------------------------------------------------


def test_unknown_version_parse_applies_no_mandates() -> None:
    """No resultType recognition and no required-_meta check under an unknown
    version; the plain superset parse still runs."""
    result = parse_as(ServerResult, {"content": [], "resultType": "anything-at-all"}, "3000-01-01")
    assert isinstance(result, CallToolResult)
    request = parse_as(ClientRequest, {"method": "tools/list"}, "3000-01-01")
    assert isinstance(request, ListToolsRequest)


def test_unknown_version_parse_still_selects_result_members_structurally() -> None:
    """Member selection is version-free; only the version-keyed mandates and the
    resultType route are off under an unknown version."""
    result = parse_as(ServerResult, {"tools": []}, "3000-01-01")
    assert isinstance(result, ListToolsResult)
    fallback = parse_as(ServerResult, {"resultType": "input_required"}, "3000-01-01")
    assert isinstance(fallback, EmptyResult)


# Result unions without an empty-result arm ------------------------------------


def test_result_union_without_empty_result_arm_parses_as_given() -> None:
    """Member selection falls back to the EmptyResult arm only where one exists;
    a union without one validates as the plain union and reports its own
    errors."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult | ListToolsResult, {"unknownKey": 1}, "2025-11-25")
    assert {error["type"] for error in exc_info.value.errors()} == {"missing"}
