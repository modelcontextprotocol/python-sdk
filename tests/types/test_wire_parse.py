"""Inbound parsing facts of the wire boundary.

Parsing is one lenient superset parse at every version, plus the 2026-07-28
mandates (an unrecognized resultType value, the reserved request _meta
entries — each with a pinned error type string — and the required method on
embedded input-request entries), structural member selection for
result-bearing unions, and the unknown-content-tag refinement.
Each test names the spec fact in plain words with its provenance class
(spec-mandated vs deployed-peer-mandated).
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    AudioContent,
    CallToolRequest,
    CallToolResult,
    CancelledNotification,
    ClientNotification,
    ClientRequest,
    ClientResult,
    CompleteResult,
    ContentBlock,
    CreateMessageResult,
    CreateMessageResultWithTools,
    DiscoverResult,
    EmptyResult,
    GetPromptResult,
    InitializeResult,
    InputRequiredResult,
    JSONRPCRequest,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListRootsRequest,
    ListToolsResult,
    ReadResourceResult,
    ServerRequest,
    ServerResult,
    ToolUseContent,
    client_result_adapter,
    server_result_adapter,
)
from mcp.types.jsonrpc import JSONRPCMessage
from mcp.types.wire import parse_as

V1 = "2024-11-05"
V4 = "2025-11-25"
D = "2026-07-28"


def error_types(exc_info: pytest.ExceptionInfo[ValidationError]) -> set[str]:
    return {error["type"] for error in exc_info.value.errors()}


def triple_meta() -> dict[str, Any]:
    return {
        PROTOCOL_VERSION_META_KEY: D,
        CLIENT_INFO_META_KEY: {"name": "c", "version": "1"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }


# --- lenient superset parse ---------------------------------------------------


@pytest.mark.parametrize("version", [V1, V4, D])
def test_unknown_fields_never_reject(version: str) -> None:
    """Unknown fields are ignored at every version, never rejected
    (deployed-peer-mandated: inbound strictness is the recorded interop
    failure mode)."""
    result = parse_as(CallToolResult, {"content": [], "futureField": {"x": 1}}, version)
    assert result == CallToolResult(content=[])


def test_audio_content_parses_even_at_2024_11_05() -> None:
    """Inbound membership is the superset at every version: audio content
    parses on a 2024-11-05 session even though that schema predates it."""
    block = parse_as(ContentBlock, {"type": "audio", "data": "QQ==", "mimeType": "audio/wav"}, V1)
    assert isinstance(block, AudioContent)


def test_future_protocol_version_value_accepted() -> None:
    """A future or unknown protocolVersion VALUE inside initialize params is
    a plain string — version acceptability is negotiation logic, not parsing
    (spec-mandated shape)."""
    request = parse_as(
        ClientRequest,
        {
            "method": "initialize",
            "params": {
                "protocolVersion": "2099-12-31",
                "capabilities": {},
                "clientInfo": {"name": "c", "version": "1"},
            },
        },
        V4,
    )
    assert request.params.protocol_version == "2099-12-31"


def test_unknown_version_string_parses_with_no_mandates() -> None:
    """An unknown version is most plausibly newer than this SDK: the parse
    stays lenient and no version-keyed mandate applies, with no exception for
    the version string itself."""
    result = parse_as(ServerResult, {"resultType": "finished"}, "2099-01-01")
    assert isinstance(result, EmptyResult)
    assert result.result_type == "finished"


# --- retention ------------------------------------------------------------------


@pytest.mark.parametrize("version", [V4, D])
def test_unknown_meta_keys_are_retained(version: str) -> None:
    """Unknown _meta keys are retained verbatim in both directions at every
    version (deployed-peer-mandated: open _meta maps everywhere)."""
    meta: dict[str, Any] = {"vendor-trace": "trace-9001"}
    if version == D:
        meta.update(triple_meta())
    payload: dict[str, Any] = {"method": "tools/call", "params": {"name": "echo", "_meta": meta}}
    request = parse_as(ClientRequest, payload, version)
    assert isinstance(request, CallToolRequest)
    assert request.params.meta is not None
    assert request.params.meta["vendor-trace"] == "trace-9001"


def test_caching_fields_retained_on_parse_at_any_version() -> None:
    """ttlMs/cacheScope are optional and retained on parse at every version
    (spec-mandated only at 2026-07-28; leniency elsewhere)."""
    result = parse_as(ListToolsResult, {"tools": [], "ttlMs": 1000, "cacheScope": "public"}, V1)
    assert result.ttl_ms == 1000
    assert result.cache_scope == "public"


def test_task_metadata_surfaced_on_2025_11_25_parse() -> None:
    request = parse_as(ClientRequest, {"method": "tools/call", "params": {"name": "t", "task": {"ttl": 5}}}, V4)
    assert isinstance(request, CallToolRequest)
    assert request.params.task is not None
    assert request.params.task.ttl == 5


# --- resultType mandate (2026-07-28) ---------------------------------------------


def test_unrecognized_result_type_rejects_at_2026_07_28() -> None:
    """resultType discriminates result handling from 2026-07-28; a value the
    revision does not define must reject so the client never misreads a
    result kind (spec-mandated). Pinned error type: result_type_invalid."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, {"resultType": "finished"}, D)
    assert error_types(exc_info) == {"result_type_invalid"}


def test_unrecognized_result_type_on_concrete_result_also_rejects() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult, {"content": [], "resultType": "finished"}, D)
    assert error_types(exc_info) == {"result_type_invalid"}


def test_absent_result_type_accepted_with_no_materialization() -> None:
    """Absent means "complete"; the parsed field stays None (spec-mandated)."""
    result = parse_as(CallToolResult, {"content": []}, D)
    assert result.result_type is None


def test_recognized_result_type_retained() -> None:
    result = parse_as(CallToolResult, {"content": [], "resultType": "complete"}, D)
    assert result.result_type == "complete"


def test_any_result_type_accepted_below_2026_07_28() -> None:
    """Earlier versions never reject the field — strictly-more-lenient parse
    (sanctioned leniency flip)."""
    result = parse_as(ServerResult, {"resultType": "finished"}, V4)
    assert isinstance(result, EmptyResult)
    assert result.result_type == "finished"


def test_stray_result_type_on_a_request_stays_accepted() -> None:
    """The mandate is scoped to results: on a request the key is an ordinary
    unknown field (never rejected)."""
    payload = {"method": "tools/call", "params": {"name": "t", "_meta": triple_meta()}, "resultType": "bogus"}
    request = parse_as(ClientRequest, payload, D)
    assert isinstance(request, CallToolRequest)


# --- reserved _meta mandate (2026-07-28, server side) ------------------------------


def test_missing_meta_container_rejects_at_2026_07_28() -> None:
    """Every 2026-07-28 client request carries the three reserved _meta
    entries (spec-mandated). Pinned error type: missing_required_meta."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ClientRequest, {"method": "tools/list"}, D)
    assert error_types(exc_info) == {"missing_required_meta"}
    assert len(exc_info.value.errors()) == 3  # each entry independently required


def test_partial_triple_rejects_at_2026_07_28() -> None:
    payload = {
        "method": "tools/call",
        "params": {
            "name": "echo",
            "arguments": {"text": "hi"},
            "_meta": {
                PROTOCOL_VERSION_META_KEY: D,
                CLIENT_INFO_META_KEY: {"name": "meta-fixture-client", "version": "1.0.0"},
            },
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ClientRequest, payload, D)
    assert error_types(exc_info) == {"missing_required_meta"}
    (error,) = exc_info.value.errors()
    assert error["loc"] == ("params", "_meta", CLIENT_CAPABILITIES_META_KEY)


def test_full_triple_parses() -> None:
    payload = {"method": "tools/call", "params": {"name": "echo", "_meta": triple_meta()}}
    request = parse_as(ClientRequest, payload, D)
    assert isinstance(request, CallToolRequest)


def test_no_triple_needed_below_2026_07_28() -> None:
    request = parse_as(ClientRequest, {"method": "tools/call", "params": {"name": "echo"}}, V4)
    assert isinstance(request, CallToolRequest)


def test_notifications_never_need_the_triple() -> None:
    """The mandate covers client requests only; notifications have no
    reserved-entry requirement (spec-mandated scope)."""
    notification = parse_as(ClientNotification, {"method": "notifications/cancelled", "params": {}}, D)
    assert isinstance(notification, CancelledNotification)


def test_requests_outside_the_2026_07_28_client_set_never_need_the_triple() -> None:
    """The reserved entries are required on 2026-07-28 client requests only;
    a request with any other method parses without them."""
    request = parse_as(ServerRequest, {"method": "roots/list"}, D)
    assert isinstance(request, ListRootsRequest)


# --- embedded input-request entries (2026-07-28) -------------------------------------


def test_input_request_entry_without_method_rejects_structurally() -> None:
    """inputRequests values are full request payloads, so method is required
    on each entry; an entry with no method is a structural failure — plain
    missing-field error, never an unknown union member (spec-mandated)."""
    payload = {
        "resultType": "input_required",
        "inputRequests": {"elicit-1": {"params": {"message": "Please provide your GitHub username"}}},
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, payload, D)
    assert error_types(exc_info) == {"missing"}
    (error,) = exc_info.value.errors()
    assert error["loc"] == ("inputRequests", "elicit-1", "method")


def test_input_request_entries_with_methods_parse() -> None:
    payload: dict[str, Any] = {
        "resultType": "input_required",
        "inputRequests": {
            "elicit-1": {
                "method": "elicitation/create",
                "params": {"message": "username?", "mode": "form", "requestedSchema": {"type": "object"}},
            },
            "roots-1": {"method": "roots/list"},
        },
    }
    result = parse_as(ServerResult, payload, D)
    assert isinstance(result, InputRequiredResult)
    assert result.input_requests is not None
    assert set(result.input_requests) == {"elicit-1", "roots-1"}


# --- resultType discrimination (2026-07-28, unions only) --------------------------------


def test_input_required_body_routes_to_input_required_arm() -> None:
    """2026-07-28 response bodies discriminate by resultType: an
    input-required body resolves to InputRequiredResult even when it carries
    fields of another member (spec-mandated)."""
    payload = {
        "resultType": "input_required",
        "content": [{"type": "text", "text": "partial"}],
        "requestState": "opaque",
    }
    result = parse_as(ServerResult, payload, D)
    assert isinstance(result, InputRequiredResult)
    assert result.request_state == "opaque"


def test_complete_body_with_content_parses_as_call_tool_result() -> None:
    payload = {"resultType": "complete", "content": [{"type": "text", "text": "done"}]}
    result = parse_as(ServerResult, payload, D)
    assert isinstance(result, CallToolResult)


def test_concrete_type_is_never_rerouted() -> None:
    """parse_as(CallToolResult, ...) returns a CallToolResult or fails on its
    own terms — the discrimination applies to union targets only, so the
    annotated return type is honest."""
    payload: dict[str, Any] = {"resultType": "input_required", "content": []}
    result = parse_as(CallToolResult, payload, D)
    assert isinstance(result, CallToolResult)
    assert result.result_type == "input_required"


def test_union_without_the_input_required_arm_is_untouched() -> None:
    """The reroute needs the input-required arm in the union; a result union
    without it parses structurally as usual."""
    result = parse_as(ClientResult, {"resultType": "input_required"}, D)
    assert isinstance(result, EmptyResult)


# --- structural member selection for result unions --------------------------------------


def test_discover_result_missing_supported_versions_rejects() -> None:
    """supportedVersions is required on a discover result; a body carrying
    the discover key set but missing it must reject as invalid params, not
    quietly parse as an empty result (spec-mandated)."""
    payload = {
        "capabilities": {},
        "serverInfo": {"name": "probe-server", "version": "0.1.0"},
        "ttlMs": 1000,
        "cacheScope": "public",
        "resultType": "complete",
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, payload, D)
    assert error_types(exc_info) == {"missing"}


def test_unknown_shaped_result_bodies_still_parse_as_empty_result() -> None:
    """A body matching no member better than the base result shape parses as
    the EmptyResult arm — unknown shapes are not rejected (leniency)."""
    result = parse_as(ServerResult, {"someVendorKey": 1}, V4)
    assert isinstance(result, EmptyResult)


def test_complete_discover_result_parses_via_selection() -> None:
    payload = {
        "supportedVersions": [V4, D],
        "capabilities": {},
        "serverInfo": {"name": "s", "version": "1"},
        "ttlMs": 0,
        "cacheScope": "private",
        "resultType": "complete",
    }
    result = parse_as(ServerResult, payload, D)
    assert isinstance(result, DiscoverResult)


# --- identical-key-set sibling arms (ranked candidate trial) -----------------------------

# The monolith splits the schema's single sampling result into a single-content
# arm and an array-content arm with the same top-level wire keys, so key-count
# ranking alone cannot order them; routing tries every structurally matching
# arm, best match first, and the first that validates wins.


@pytest.mark.parametrize("version", [V1, V4, D])
def test_sampling_with_tools_body_parses_as_the_array_content_arm(version: str) -> None:
    """A sampling response whose content is an array with a tool-use block
    (legal wire shape since 2025-11-25) is rejected by the single-content arm
    and must fall through to the array-content arm; inbound membership is
    never version-gated (spec-mandated shape, superset parse)."""
    body: dict[str, Any] = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "checking the weather"},
            {"type": "tool_use", "id": "call-1", "name": "get_weather", "input": {}},
        ],
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
    body: dict[str, Any] = {
        "role": "assistant",
        "content": {"type": "text", "text": "sunny"},
        "model": "example-model",
    }
    result = parse_as(ClientResult, body, V4)
    assert isinstance(result, CreateMessageResult)


def test_result_body_rejected_with_the_best_matching_arms_errors_when_no_arm_validates() -> None:
    """A body keyed like a discover result but missing its required
    supportedVersions matches several arms structurally and validates as none
    of them; the reject surfaces the best-matching arm's own errors."""
    body: dict[str, Any] = {
        "capabilities": {},
        "serverInfo": {"name": "probe-server", "version": "0.1.0"},
        "ttlMs": 1000,
        "cacheScope": "public",
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, body, D)
    (error,) = exc_info.value.errors()
    assert error["type"] == "missing"
    assert error["loc"] == ("supportedVersions",)


def _wire_keys(cls: type[BaseModel]) -> frozenset[str]:
    """A model's top-level wire key set (each field's alias when it has one)."""
    return frozenset(info.alias or name for name, info in cls.model_fields.items())


def _tie_groups(union: Any) -> list[list[type[BaseModel]]]:
    """Arms of a result union sharing one top-level wire key set, in order."""
    groups: dict[frozenset[str], list[type[BaseModel]]] = {}
    for arm in get_args(union):
        groups.setdefault(_wire_keys(arm), []).append(arm)
    return [arms for arms in groups.values() if len(arms) > 1]


def test_tie_groups_resolve_exactly_like_the_plain_union_adapter() -> None:
    """Mechanically derive the arms sharing a top-level wire key set in each
    public result union: key counting cannot order such siblings, so for
    bodies shaped like a tie group's members parse_as must agree with the
    plain smart-union adapter's resolution class. Today the only tie group is
    the sampling-result split; a new arm joining a tie group fails this pin
    and must bring its own routing tests."""
    assert _tie_groups(ServerResult) == []
    assert _tie_groups(ClientResult) == [[CreateMessageResult, CreateMessageResultWithTools]]
    single: dict[str, Any] = {"role": "assistant", "content": {"type": "text", "text": "hi"}, "model": "m"}
    array: dict[str, Any] = {"role": "assistant", "content": [{"type": "text", "text": "hi"}], "model": "m"}
    for body in (single, array):
        assert type(parse_as(ClientResult, body, V4)) is type(client_result_adapter.validate_python(body))


# --- unknown content type refinement ------------------------------------------------------


@pytest.mark.parametrize("version", [V1, V4, D])
def test_unknown_content_type_rejects_at_every_version(version: str) -> None:
    """The content union is closed in every deployed SDK: an unknown type tag
    is an unknown union member at every version (deployed-peer-mandated).
    Pinned error type: union_tag_invalid."""
    payload = {"type": "holographic", "data": "QmFzZTY0", "mimeType": "model/vnd.example-hologram"}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ContentBlock, payload, version)
    assert error_types(exc_info) == {"union_tag_invalid"}


@pytest.mark.parametrize("version", [V4, D])
def test_unknown_content_type_nested_in_a_result_rejects(version: str) -> None:
    """The refinement reaches tags failing nested inside a parsed result's
    content list, with the error located at the failing item."""
    payload = {"resultType": "complete", "content": [{"type": "carousel-deck", "slides": ["aGVsbG8="]}]}
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, payload, version)
    assert error_types(exc_info) == {"union_tag_invalid"}
    (error,) = exc_info.value.errors()
    assert error["loc"] == ("content", 0)


def test_unknown_tag_among_valid_siblings_rejects() -> None:
    payload: dict[str, Any] = {
        "resultType": "complete",
        "content": [
            {"type": "text", "text": "ok"},
            {"type": "carousel-deck", "slides": []},
        ],
    }
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ServerResult, payload, V4)
    (error,) = exc_info.value.errors()
    assert error["loc"] == ("content", 1)


def test_known_tag_with_bad_fields_keeps_structural_errors() -> None:
    """A recognized tag with invalid fields is not an unknown member; the
    structural errors pass through untouched."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ContentBlock, {"type": "text"}, V4)
    assert "union_tag_invalid" not in error_types(exc_info)


def test_tag_less_text_content_parses_via_the_defaulted_tag() -> None:
    """The monolith content models default their type tag, so a tag-less dict
    that satisfies one member's fields parses as that member (the lenient v1
    behavior, unchanged)."""
    block = parse_as(ContentBlock, {"text": "no tag at all"}, V4)
    assert block == parse_as(ContentBlock, {"type": "text", "text": "no tag at all"}, V4)


def test_tag_less_content_failing_every_member_keeps_structural_errors() -> None:
    """A tag-less dict that fits no member is a structural failure, not an
    unknown union member."""
    with pytest.raises(ValidationError) as exc_info:
        parse_as(ContentBlock, {}, V4)
    assert "union_tag_invalid" not in error_types(exc_info)


def test_non_dict_content_item_keeps_structural_errors() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_as(CallToolResult, {"content": [42]}, V4)
    assert "union_tag_invalid" not in error_types(exc_info)


# --- envelope frames --------------------------------------------------------------------------


def test_envelope_frame_parses_at_envelope_level_only() -> None:
    """Frame parsing types the envelope; generic bodies stay untyped dicts,
    so no payload mandate reaches inside them."""
    frame = parse_as(JSONRPCMessage, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, D)
    assert isinstance(frame, JSONRPCRequest)
    assert frame.params is None


# --- resolution pins for the public result adapter ---------------------------------------------

# One typed frame per arm the union carried before the 2026-07-28 growth, the
# two minimal bodies, and one 2026-07-28-shaped frame. The plain smart-union
# adapter is public API; these pins freeze its resolution so growing the
# union can never silently re-route an existing frame.
_RESOLUTION_PINS: list[tuple[dict[str, Any], type[Any]]] = [
    (
        {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "s", "version": "1"}},
        InitializeResult,
    ),
    ({"completion": {"values": []}}, CompleteResult),
    ({"messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}]}, GetPromptResult),
    ({"prompts": []}, ListPromptsResult),
    ({"resources": []}, ListResourcesResult),
    ({"resourceTemplates": []}, ListResourceTemplatesResult),
    ({"contents": []}, ReadResourceResult),
    ({"content": [{"type": "text", "text": "hi"}]}, CallToolResult),
    ({"tools": []}, ListToolsResult),
    ({}, EmptyResult),
    ({"_meta": {"vendor": "x"}}, EmptyResult),
    # The full 2026-07-28 server/discover result key set; supportedVersions
    # exists in no earlier published schema, so no released-version peer can
    # produce this frame. It resolves to the discover arm and stays accepted
    # — a deliberate, pinned outcome of growing the union.
    (
        {
            "supportedVersions": ["2025-11-25", "2026-07-28"],
            "capabilities": {},
            "serverInfo": {"name": "s", "version": "1"},
        },
        DiscoverResult,
    ),
]


@pytest.mark.parametrize(
    ("payload", "expected"),
    _RESOLUTION_PINS,
    ids=[f"{index}-{expected.__name__}" for index, (_, expected) in enumerate(_RESOLUTION_PINS)],
)
def test_server_result_adapter_resolution_is_pinned(payload: dict[str, Any], expected: type[Any]) -> None:
    """Every frame resolvable before the union grew still resolves to the
    same class, and the minimal bodies stay EmptyResult — the appended
    all-optional input-required arm absorbs nothing."""
    resolved = server_result_adapter.validate_python(payload)
    assert type(resolved) is expected
