"""Emission facts of the wire boundary, one (+)/(-) pair per version-keyed rule.

Each test names the spec fact it pins in plain words, with its provenance
class: spec-mandated (the published schema or spec prose requires it) or
deployed-peer-mandated (a behavior real deployed SDKs enforce on the wire).
Negative tests assert byte identity against the plain monolith dump via
``json.dumps`` so key order is part of the guarantee.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import BaseModel, FileUrl, ValidationError

from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    LOG_LEVEL_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    AudioContent,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    ClientCapabilities,
    CompleteResult,
    Completion,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    DiscoverResult,
    ElicitCompleteNotification,
    ElicitCompleteNotificationParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    EmptyResult,
    ErrorData,
    GetPromptResult,
    Icon,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeRequestParams,
    InputRequiredResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsRequest,
    ListRootsResult,
    ListToolsRequest,
    ListToolsResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    PaginatedRequestParams,
    PingRequest,
    ProgressNotification,
    ProgressNotificationParams,
    PromptMessage,
    RequestParamsMeta,
    ResourceLink,
    Root,
    RootsCapability,
    SamplingMessage,
    ServerCapabilities,
    SubscribeRequest,
    SubscribeRequestParams,
    SubscriptionFilter,
    SubscriptionsListenRequest,
    SubscriptionsListenRequestParams,
    TaskMetadata,
    TextContent,
    Tool,
    ToolUseContent,
)
from mcp.types.wire import (
    UnknownProtocolVersionError,
    UnsupportedAtVersionError,
    _merge_and_align,  # tested directly: the defect guard is unreachable via valid packages
    serialize_for,
)

V1 = "2024-11-05"
V2 = "2025-03-26"
V3 = "2025-06-18"
V4 = "2025-11-25"
D = "2026-07-28"
RELEASED = (V1, V2, V3, V4)


def monolith_dump(model: BaseModel) -> dict[str, Any]:
    """The plain user dump — the byte-identity reference for released versions."""
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def as_bytes(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=False)


def identity_meta() -> dict[str, Any]:
    """The caller-supplied session identity a 2026-07-28 client request needs."""
    return {
        CLIENT_INFO_META_KEY: {"name": "example-client", "version": "1.0.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }


def as_meta(entries: dict[str, Any]) -> RequestParamsMeta:
    """Build a params _meta value from plain entries (the open-map wire form)."""
    return cast("RequestParamsMeta", entries)


# --- payload domain and version registry ---------------------------------


@pytest.mark.parametrize(
    "fragment",
    [
        TextContent(text="x"),
        ClientCapabilities(),
        SamplingMessage(role="user", content=TextContent(text="x")),
        PaginatedRequestParams(),
    ],
    ids=lambda fragment: type(fragment).__name__,
)
def test_serialize_for_refuses_bare_fragments(fragment: BaseModel) -> None:
    """Fragments are shaped only inside the body that carries them; a bare
    fragment is a programming error, refused identically at every version."""
    with pytest.raises(TypeError, match="message body or an envelope model"):
        serialize_for(fragment, V4)


def test_bare_fragment_refused_before_the_version_check() -> None:
    """Argument validation precedes version lookup: (bare fragment, unknown
    version) deterministically raises TypeError."""
    with pytest.raises(TypeError):
        serialize_for(TextContent(text="x"), "not-a-version")


def test_serialize_for_unknown_version() -> None:
    """Emission never guesses a wire shape for a version it does not know."""
    with pytest.raises(UnknownProtocolVersionError) as exc_info:
        serialize_for(EmptyResult(), "2030-01-01")
    assert exc_info.value.version == "2030-01-01"
    assert exc_info.value.known == (V1, V2, V3, V4, D)


# --- envelope frames (version-independent) --------------------------------


@pytest.mark.parametrize("version", [V1, V4, D])
def test_envelope_request_emits_verbatim(version: str) -> None:
    """JSON-RPC envelope frames are identical in every protocol version; a
    bodyless request emits without a params key (spec-mandated)."""
    frame = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    assert serialize_for(frame, version) == {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def test_envelope_notification_emits_verbatim() -> None:
    frame = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    assert serialize_for(frame, V1) == {"jsonrpc": "2.0", "method": "notifications/initialized"}


def test_envelope_error_frame_emits_verbatim() -> None:
    """Error frames carry id and the error object unchanged (spec-mandated)."""
    frame = JSONRPCError(jsonrpc="2.0", id=5, error=ErrorData(code=-32601, message="Method not found"))
    assert serialize_for(frame, V1) == {
        "jsonrpc": "2.0",
        "id": 5,
        "error": {"code": -32601, "message": "Method not found"},
    }


def test_generic_envelope_interiors_are_opaque() -> None:
    """The untyped result interior of a generic envelope passes through with
    no injection and no strip — payload shaping applies only to typed payload
    models, never by guessing what an untyped dict holds."""
    frame = JSONRPCResponse(jsonrpc="2.0", id=2, result={"resultType": "complete", "ttlMs": 9})
    assert serialize_for(frame, V1)["result"] == {"resultType": "complete", "ttlMs": 9}


# --- identity: released-version dumps are byte-identical ------------------

_IDENTITY_CASES: list[BaseModel] = [
    PingRequest(),
    InitializeRequest(
        params=InitializeRequestParams(
            protocol_version=V2,
            capabilities=ClientCapabilities(roots=RootsCapability(list_changed=True)),
            client_info=Implementation(name="example-client", version="1.0.0"),
        )
    ),
    # A request whose params._meta carries user-set reserved keys and a vendor
    # key: _meta entries are retained verbatim on emission at every version
    # (deployed-peer-mandated: open _meta maps in all deployed SDKs).
    CallToolRequest(
        params=CallToolRequestParams(
            name="echo",
            arguments={"text": "hi"},
            _meta={
                PROTOCOL_VERSION_META_KEY: D,
                CLIENT_INFO_META_KEY: {"name": "example-client", "version": "1.0.0"},
                CLIENT_CAPABILITIES_META_KEY: {},
                LOG_LEVEL_META_KEY: "info",
                "vendor-trace": "trace-9001",
            },
        )
    ),
    SubscribeRequest(params=SubscribeRequestParams(uri="file:///r")),
    ListRootsRequest(),
    CreateMessageRequest(
        params=CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=TextContent(text="q"))], max_tokens=10
        )
    ),
    InitializedNotification(),
    CancelledNotification(params=CancelledNotificationParams(request_id=7)),
    ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=0.5)),
    LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="x")),
    EmptyResult(),
    CallToolResult(content=[TextContent(text="hello")]),
    ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})]),
    GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="hi"))]),
    CompleteResult(completion=Completion(values=["a"])),
    ListRootsResult(roots=[Root(uri=FileUrl("file:///workspace"))]),
    CreateMessageResult(role="assistant", content=TextContent(text="ok"), model="m"),
]


@pytest.mark.parametrize("version", RELEASED)
@pytest.mark.parametrize("model", _IDENTITY_CASES, ids=lambda model: type(model).__name__)
def test_released_version_emission_is_byte_identical(model: BaseModel, version: str) -> None:
    """For values valid at the target released version, emission is the plain
    monolith dump byte for byte — same keys, same order, same values."""
    assert as_bytes(serialize_for(model, version)) == as_bytes(monolith_dump(model))


# --- resultType ------------------------------------------------------------


def test_result_type_injected_on_2026_07_28_emission() -> None:
    """resultType is required on 2026-07-28 results; an unset field emits as
    "complete" (spec-mandated)."""
    out = serialize_for(CallToolResult(content=[TextContent(text="hello")]), D)
    assert out == {"content": [{"type": "text", "text": "hello"}], "isError": False, "resultType": "complete"}


def test_result_type_user_value_never_clobbered() -> None:
    out = serialize_for(CallToolResult(content=[], result_type="complete"), D)
    assert out["resultType"] == "complete"


def test_input_required_result_announces_itself() -> None:
    """An input-required result emits resultType "input_required" with its
    embedded requests intact (spec-mandated)."""
    result = InputRequiredResult(request_state="opaque-state")
    out = serialize_for(result, D)
    assert out == {"requestState": "opaque-state", "resultType": "input_required"}


def test_result_type_stripped_below_2026_07_28() -> None:
    """Even a user-set resultType is dropped on earlier versions: deployed
    peers reject an empty result carrying any extra key, and retention
    without the strip is exactly that failure (deployed-peer-mandated)."""
    with_field = CallToolResult(content=[TextContent(text="hello")], result_type="complete")
    without_field = CallToolResult(content=[TextContent(text="hello")])
    assert as_bytes(serialize_for(with_field, V4)) == as_bytes(monolith_dump(without_field))


@pytest.mark.parametrize("version", [V1, V4])
def test_empty_result_dumps_exactly_empty(version: str) -> None:
    """An empty result is exactly {} on released versions — deployed peers
    hard-reject any extra key there (deployed-peer-mandated)."""
    assert as_bytes(serialize_for(EmptyResult(), version)) == "{}"


def test_empty_result_carries_result_type_at_2026_07_28() -> None:
    assert serialize_for(EmptyResult(), D) == {"resultType": "complete"}


# --- caching directives ----------------------------------------------------


def test_caching_defaults_injected_on_2026_07_28() -> None:
    """ttlMs/cacheScope are required on cacheable results from 2026-07-28;
    unset fields get the don't-cache pair (spec-mandated requiredness, SDK
    default choice)."""
    out = serialize_for(ListToolsResult(tools=[]), D)
    assert out["ttlMs"] == 0
    assert out["cacheScope"] == "private"


def test_caching_user_values_pass_unclobbered() -> None:
    out = serialize_for(ListToolsResult(tools=[], ttl_ms=5000, cache_scope="public"), D)
    assert out["ttlMs"] == 5000
    assert out["cacheScope"] == "public"


def test_caching_fields_stripped_below_2026_07_28() -> None:
    """User-set caching directives are dropped on versions that predate them;
    the rest of the body is byte-identical (spec: the fields do not exist in
    earlier schemas)."""
    with_fields = ListToolsResult(tools=[], ttl_ms=5000, cache_scope="public")
    without_fields = ListToolsResult(tools=[])
    assert as_bytes(serialize_for(with_fields, V4)) == as_bytes(monolith_dump(without_fields))


def test_discover_result_emits_with_policy_defaults_at_2026_07_28() -> None:
    result = DiscoverResult(
        supported_versions=[V4, D],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="fixture-server", version="1.0.0"),
    )
    out = serialize_for(result, D)
    assert out["supportedVersions"] == [V4, D]
    assert out["ttlMs"] == 0
    assert out["cacheScope"] == "private"
    assert out["resultType"] == "complete"
    assert "instructions" not in out


def test_discover_result_has_no_wire_form_on_released_versions() -> None:
    """server/discover and its result exist only in the 2026-07-28 schema."""
    result = DiscoverResult(
        supported_versions=[D], capabilities=ServerCapabilities(), server_info=Implementation(name="s", version="1")
    )
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(result, V4)


# --- reserved _meta entries on client requests ----------------------------


def test_protocol_version_injected_into_request_meta_at_2026_07_28() -> None:
    """2026-07-28 client requests carry the reserved _meta entries; the
    boundary derives and merges protocolVersion, materializing params and
    _meta when the handler left them unset (spec-mandated)."""
    request = CallToolRequest(
        params=CallToolRequestParams(name="get-weather", arguments={"city": "Berlin"}, _meta=as_meta(identity_meta()))
    )
    out = serialize_for(request, D)
    assert out["params"]["_meta"][PROTOCOL_VERSION_META_KEY] == D
    assert out["params"]["_meta"][CLIENT_INFO_META_KEY] == {"name": "example-client", "version": "1.0.0"}
    assert out["params"]["_meta"][CLIENT_CAPABILITIES_META_KEY] == {}
    assert out["params"]["name"] == "get-weather"
    assert out["params"]["arguments"] == {"city": "Berlin"}


def test_protocol_version_merge_never_overwrites_a_caller_value() -> None:
    meta = identity_meta() | {PROTOCOL_VERSION_META_KEY: "caller-pinned"}
    request = ListToolsRequest(params=PaginatedRequestParams(_meta=as_meta(meta)))
    out = serialize_for(request, D)
    assert out["params"]["_meta"][PROTOCOL_VERSION_META_KEY] == "caller-pinned"


def test_progress_token_coexists_with_the_reserved_entries() -> None:
    meta = identity_meta() | {"progressToken": "tok-1"}
    out = serialize_for(ListToolsRequest(params=PaginatedRequestParams(_meta=as_meta(meta))), D)
    assert out["params"]["_meta"]["progressToken"] == "tok-1"
    assert out["params"]["_meta"][PROTOCOL_VERSION_META_KEY] == D


def test_missing_session_identity_refuses_at_2026_07_28() -> None:
    """The boundary never synthesizes clientInfo/clientCapabilities — they
    are session identity. A bare request has no legal 2026-07-28 wire form
    (the schema requires all three reserved entries)."""
    with pytest.raises(UnsupportedAtVersionError) as exc_info:
        serialize_for(ListToolsRequest(), D)
    assert exc_info.value.version == D
    assert isinstance(exc_info.value.__cause__, ValidationError)
    # Two entries are missing; the message carries one and counts the rest.
    assert "more" in str(exc_info.value)


def test_partially_missing_session_identity_also_refuses() -> None:
    request = ListToolsRequest(
        params=PaginatedRequestParams(_meta={CLIENT_INFO_META_KEY: {"name": "c", "version": "1"}})
    )
    with pytest.raises(UnsupportedAtVersionError) as exc_info:
        serialize_for(request, D)
    assert "clientCapabilities" in str(exc_info.value)


def test_nothing_injected_below_2026_07_28() -> None:
    """On earlier versions an unset params stays omitted — the dump is the
    plain monolith dump (deployed-peer-mandated byte identity)."""
    assert as_bytes(serialize_for(ListToolsRequest(), V4)) == as_bytes(monolith_dump(ListToolsRequest()))


# --- capabilities ----------------------------------------------------------


def test_roots_capability_emits_empty_at_2026_07_28() -> None:
    """2026-07-28 removed roots.listChanged; the capability itself survives
    and emits as the empty object (spec-mandated)."""
    request = ListToolsRequest(
        params=PaginatedRequestParams(
            _meta={
                CLIENT_INFO_META_KEY: Implementation(name="ExampleClient", version="1.0.0"),
                CLIENT_CAPABILITIES_META_KEY: ClientCapabilities(roots=RootsCapability(list_changed=True)),
            }
        )
    )
    out = serialize_for(request, D)
    assert out == {
        "method": "tools/list",
        "params": {
            "_meta": {
                CLIENT_INFO_META_KEY: {"name": "ExampleClient", "version": "1.0.0"},
                CLIENT_CAPABILITIES_META_KEY: {"roots": {}},
                PROTOCOL_VERSION_META_KEY: D,
            }
        },
    }


def test_capabilities_extensions_stripped_below_2026_07_28() -> None:
    """The extensions field is new in 2026-07-28 and must not leak by default
    on earlier versions; sibling capability keys are untouched."""

    def initialize(extensions: dict[str, Any] | None) -> InitializeRequest:
        capabilities = ClientCapabilities(roots=RootsCapability(list_changed=True), extensions=extensions)
        return InitializeRequest(
            params=InitializeRequestParams(
                protocol_version=V4, capabilities=capabilities, client_info=Implementation(name="c", version="1")
            )
        )

    with_extensions = initialize({"io.modelcontextprotocol/oauth-client-credentials": {}})
    assert as_bytes(serialize_for(with_extensions, V4)) == as_bytes(monolith_dump(initialize(None)))


def test_capabilities_extensions_emitted_at_2026_07_28() -> None:
    """Client extensions ride the _meta clientCapabilities projection at
    2026-07-28 (spec-mandated: the field exists there)."""
    meta = {
        CLIENT_INFO_META_KEY: {"name": "c", "version": "1"},
        CLIENT_CAPABILITIES_META_KEY: ClientCapabilities(extensions={"io.modelcontextprotocol/x": {}}),
    }
    out = serialize_for(ListToolsRequest(params=PaginatedRequestParams(_meta=as_meta(meta))), D)
    assert out["params"]["_meta"][CLIENT_CAPABILITIES_META_KEY] == {"extensions": {"io.modelcontextprotocol/x": {}}}


def test_server_extensions_emitted_in_discover_result() -> None:
    result = DiscoverResult(
        supported_versions=[D],
        capabilities=ServerCapabilities(extensions={"io.modelcontextprotocol/y": {}}),
        server_info=Implementation(name="s", version="1"),
    )
    assert serialize_for(result, D)["capabilities"] == {"extensions": {"io.modelcontextprotocol/y": {}}}


def test_capability_extension_values_admit_every_json_type_at_2026_07_28() -> None:
    """Extension values are arbitrary JSON, so fractional numbers and nulls at
    any depth survive the 2026-07-28 revalidation (spec-mandated: the schema
    source types extension values as any JSON value)."""
    extension_value = {"ratio": 0.5, "experimental": None, "steps": [1.5, None, "done"]}
    meta = {
        CLIENT_INFO_META_KEY: {"name": "c", "version": "1"},
        CLIENT_CAPABILITIES_META_KEY: ClientCapabilities(extensions={"io.modelcontextprotocol/x": extension_value}),
    }
    out = serialize_for(ListToolsRequest(params=PaginatedRequestParams(_meta=as_meta(meta))), D)
    emitted = out["params"]["_meta"][CLIENT_CAPABILITIES_META_KEY]["extensions"]["io.modelcontextprotocol/x"]
    assert emitted == extension_value


# --- tasks (2025-11-25 only) ------------------------------------------------


def test_task_metadata_emitted_at_2025_11_25() -> None:
    """The task field on augmentable params exists only in the 2025-11-25
    schema (spec-mandated)."""
    request = CallToolRequest(params=CallToolRequestParams(name="t", task=TaskMetadata(ttl=60_000)))
    assert serialize_for(request, V4)["params"]["task"] == {"ttl": 60000}


@pytest.mark.parametrize("version", [V3, D])
def test_task_metadata_stripped_outside_2025_11_25(version: str) -> None:
    meta = as_meta(identity_meta()) if version == D else None

    def request(task: TaskMetadata | None) -> CallToolRequest:
        return CallToolRequest(params=CallToolRequestParams(name="t", task=task, _meta=meta))

    out = serialize_for(request(TaskMetadata(ttl=60_000)), version)
    assert "task" not in out["params"]
    if version == V3:
        assert as_bytes(out) == as_bytes(monolith_dump(request(None)))


def _initialize_with_tasks(protocol_version: str, tasks: dict[str, Any] | None) -> InitializeRequest:
    capabilities = ClientCapabilities() if tasks is None else ClientCapabilities.model_validate({"tasks": tasks})
    return InitializeRequest(
        params=InitializeRequestParams(
            protocol_version=protocol_version,
            capabilities=capabilities,
            client_info=Implementation(name="c", version="1"),
        )
    )


def test_tasks_capability_subtree_emitted_at_2025_11_25() -> None:
    request = _initialize_with_tasks(V4, {"requests": {"sampling": {"createMessage": {}}}})
    out = serialize_for(request, V4)
    assert out["params"]["capabilities"]["tasks"] == {"requests": {"sampling": {"createMessage": {}}}}


def test_tasks_capability_subtree_stripped_below_2025_11_25() -> None:
    with_tasks = _initialize_with_tasks(V3, {"requests": {"sampling": {"createMessage": {}}}})
    without_tasks = _initialize_with_tasks(V3, None)
    assert as_bytes(serialize_for(with_tasks, V3)) == as_bytes(monolith_dump(without_tasks))


# --- newer optional fields pass through (no narrowing) ---------------------


def test_icons_and_title_pass_through_on_older_versions() -> None:
    """New optional fields on known types are wire-safe against every
    deployed peer; emission never strips them on versions that predate them
    (deployed-peer-mandated: no gating needed)."""
    result = ListToolsResult(
        tools=[Tool(name="t", title="T", input_schema={"type": "object"}, icons=[Icon(src="https://e/i.png")])]
    )
    for version in (V1, V3):
        out = serialize_for(result, version)
        assert out["tools"][0]["title"] == "T"
        assert out["tools"][0]["icons"] == [{"src": "https://e/i.png"}]
        assert as_bytes(out) == as_bytes(monolith_dump(result))


@pytest.mark.parametrize("version", [V1, V3, D])
def test_scalar_structured_content_passes_at_every_version(version: str) -> None:
    """Values are never narrowed on emission: a non-object structuredContent
    passes through unchanged everywhere."""
    out = serialize_for(CallToolResult(content=[], structured_content=5), version)
    assert out["structuredContent"] == 5


def test_unset_structured_content_is_absent() -> None:
    out = serialize_for(CallToolResult(content=[]), D)
    assert "structuredContent" not in out


def test_object_structured_content_emitted_at_2026_07_28() -> None:
    out = serialize_for(
        CallToolResult(content=[TextContent(text="22.5 C")], structured_content={"temperature": 22.5}), D
    )
    assert out["structuredContent"] == {"temperature": 22.5}
    assert out["resultType"] == "complete"


def test_opened_tool_schemas_pass_through_unchanged() -> None:
    """Tool input schemas accept the full JSON Schema vocabulary; every
    keyword — including $ref/$defs and conditionals — survives emission
    verbatim (spec-mandated: the schemas leave these objects open)."""
    schema = {
        "type": "object",
        "properties": {"query": {"$ref": "#/$defs/nonEmptyString"}},
        "required": ["query"],
        "if": {"required": ["mode"]},
        "then": {"required": ["filters"]},
        "$defs": {"nonEmptyString": {"type": "string", "minLength": 1}},
    }
    result = ListToolsResult(tools=[Tool(name="search", input_schema=schema)], ttl_ms=0, cache_scope="private")
    assert serialize_for(result, D)["tools"][0]["inputSchema"] == schema


# --- content blocks ---------------------------------------------------------


def test_audio_content_passes_through_at_2024_11_05() -> None:
    """audio content entered the schema in 2025-03-26 but is deliberately not
    gated on emission to older peers (sibling parity; peers reject unknown
    blocks at request level — accepted risk)."""
    result = CallToolResult(content=[AudioContent(data="QQ==", mime_type="audio/wav")])
    out = serialize_for(result, V1)
    assert out["content"][0] == {"type": "audio", "data": "QQ==", "mimeType": "audio/wav"}


@pytest.mark.parametrize("version", [V1, V2])
def test_resource_link_passes_through_before_2025_06_18(version: str) -> None:
    result = CallToolResult(content=[ResourceLink(name="r", uri="https://example.com/r")])
    out = serialize_for(result, version)
    assert out["content"][0]["type"] == "resource_link"
    assert out["content"][0]["uri"] == "https://example.com/r"


# --- sampling and tool content bounds ---------------------------------------


def test_tool_content_refused_at_2025_06_18_and_earlier() -> None:
    """tool_use/tool_result sampling content entered the schema in
    2025-11-25; earlier revisions have no representation for it, and dropping
    it would change meaning (spec-mandated single-block content there)."""
    request = CreateMessageRequest(
        params=CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=ToolUseContent(name="t", id="1", input={}))],
            max_tokens=5,
        )
    )
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(request, V3)
    assert serialize_for(request, V4)["params"]["messages"][0]["content"]["type"] == "tool_use"


def test_array_sampling_content_refused_at_2025_06_18_and_earlier() -> None:
    """Multi-block sampling messages have no lossless collapse to the
    single-block shape of 2025-06-18 and earlier (spec-mandated)."""
    request = CreateMessageRequest(
        params=CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=[TextContent(text="a"), TextContent(text="b")])],
            max_tokens=5,
        )
    )
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(request, V3)
    out = serialize_for(request, V4)
    assert out["params"]["messages"][0]["content"] == [
        {"type": "text", "text": "a"},
        {"type": "text", "text": "b"},
    ]


def test_wide_sampling_result_refused_at_2025_06_18_and_earlier() -> None:
    """The wide-content sampling result is typed wide by the schemas from
    2025-11-25; through 2025-06-18 the same wire class is single-block, so
    the wide SDK class has no legal form there (spec-mandated)."""
    result = CreateMessageResultWithTools(role="assistant", content=[TextContent(text="x")], model="m")
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(result, V3)
    assert serialize_for(result, V4)["content"] == [{"type": "text", "text": "x"}]


# --- multi-round-trip results ------------------------------------------------


def test_input_required_result_refused_below_2026_07_28() -> None:
    """InputRequiredResult exists only in the 2026-07-28 schema; on earlier
    versions there is no type to validate against (spec-mandated)."""
    result = InputRequiredResult(request_state="s")
    with pytest.raises(UnsupportedAtVersionError) as exc_info:
        serialize_for(result, V4)
    assert exc_info.value.version == V4


def test_empty_input_required_result_refused() -> None:
    """The 2026-07-28 schema requires at least one of inputRequests /
    requestState on the wire; the constraint is spec prose, checked
    explicitly (spec-mandated)."""
    with pytest.raises(UnsupportedAtVersionError, match="neither input_requests nor request_state"):
        serialize_for(InputRequiredResult(), D)


def test_embedded_input_responses_pass_through_verbatim() -> None:
    """The boundary never reshapes embedded request/response payloads:
    caller-set _meta and resultType on inputResponses values survive
    2026-07-28 emission untouched (embedded hygiene is the caller's job)."""
    embedded = CreateMessageResult(
        role="assistant", content=TextContent(text="ok"), model="m", result_type="complete", _meta={"k": "v"}
    )
    request = CallToolRequest(
        params=CallToolRequestParams(name="retry-me", _meta=as_meta(identity_meta()), input_responses={"r1": embedded})
    )
    out = serialize_for(request, D)
    entry = out["params"]["inputResponses"]["r1"]
    assert entry["resultType"] == "complete"
    assert entry["_meta"] == {"k": "v"}


# --- elicitation and cancellation bounds -------------------------------------


def test_url_mode_elicitation_refused_at_2025_06_18() -> None:
    """URL-mode elicitation entered the schema in 2025-11-25 (spec-mandated
    version floor)."""
    request = ElicitRequest(
        params=ElicitRequestURLParams(message="auth needed", url="https://example.com/auth", elicitation_id="e-1")
    )
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(request, V3)
    assert serialize_for(request, V4)["params"]["mode"] == "url"


def test_list_string_elicit_content_refused_below_2025_11_25() -> None:
    """Multi-select (list-of-strings) elicitation values entered the schema
    in 2025-11-25 (spec-mandated)."""
    result = ElicitResult(action="accept", content={"choices": ["a", "b"]})
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(result, V3)
    assert serialize_for(result, V4)["content"] == {"choices": ["a", "b"]}


@pytest.mark.parametrize("version", [V3, V4, D])
def test_fractional_elicit_content_emits_at_every_modeled_version(version: str) -> None:
    """Form answers are string | number | boolean (string arrays from
    2025-11-25), so a fractional number is a legal elicitation answer at
    every version that models elicitation; the value keeps its exact JSON
    rendering (spec-mandated; the pinned schema renderings say "integer"
    only as a render artifact the version packages deliberately widen)."""
    result = ElicitResult(action="accept", content={"ratio": 0.5})
    out = serialize_for(result, version)
    assert out["content"] == {"ratio": 0.5}
    if version != D:  # at 2026-07-28 the injected resultType is the only delta
        assert as_bytes(out) == as_bytes(monolith_dump(result))


@pytest.mark.parametrize("version", [V3, V4, D])
def test_null_elicit_content_values_pass_through_at_every_modeled_version(version: str) -> None:
    """No schema version types a null elicitation answer — the monolith's
    None value arm exists for v1.x constructor compatibility — but emitted
    values are caller data and travel verbatim at every version that models
    elicitation, exactly as python v1.x itself constructs, accepts, and
    emits the same body (deployed-peer-mandated pass-through; a version
    package's narrower value typing decides parses, never emissions)."""
    result = ElicitResult(action="accept", content={"x": None, "y": "ok"})
    out = serialize_for(result, version)
    assert out["content"] == {"x": None, "y": "ok"}
    if version != D:  # at 2026-07-28 the injected resultType is the only delta
        assert as_bytes(out) == as_bytes(monolith_dump(result))


def test_elicit_result_has_no_wire_form_before_2025_06_18() -> None:
    """Elicitation entered the schema in 2025-06-18 (spec-mandated version
    floor); no value, fractional or not, has an earlier wire form."""
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(ElicitResult(action="accept", content={"ratio": 0.5}), V2)


@pytest.mark.parametrize("version", [V3, V4])
def test_fractional_schema_bounds_emit_byte_identically(version: str) -> None:
    """JSON Schema number bounds are numbers: a fractional minimum/maximum in
    a requested schema is legal at every version with elicitation and emits
    byte-identically (spec-mandated; integer-only bounds in the pinned
    schema renderings are the same render artifact)."""
    request = ElicitRequest(
        params=ElicitRequestFormParams(
            message="Rate this answer",
            requested_schema={
                "type": "object",
                "properties": {"score": {"type": "number", "minimum": 0.5, "maximum": 9.5}},
            },
        )
    )
    assert as_bytes(serialize_for(request, version)) == as_bytes(monolith_dump(request))


@pytest.mark.parametrize("version", [V3, V4, D])
def test_form_elicitation_schema_bounds_emit_byte_identically(version: str) -> None:
    """The requested-schema interior is caller data and travels verbatim:
    re-validation through a version package decides only which keys survive,
    never the values — so a fractional bound keeps its exact JSON rendering
    (1.0 stays 1.0) and an integral one is never re-rendered (120 stays 120),
    whatever numeric kind the target version's package declares for the field
    (deployed-peer-mandated byte identity)."""
    request = ElicitRequest(
        params=ElicitRequestFormParams(
            message="How old are you?",
            requested_schema={
                "type": "object",
                "properties": {"age": {"type": "number", "minimum": 1.0, "maximum": 120}},
            },
        )
    )
    assert as_bytes(serialize_for(request, version)) == as_bytes(monolith_dump(request))


def test_cancelled_notification_requires_request_id_through_2025_06_18() -> None:
    """requestId on a cancellation is required through 2025-06-18 and
    optional from 2025-11-25 (spec-mandated)."""
    without_id = CancelledNotification(params=CancelledNotificationParams(reason="bored"))
    with pytest.raises(UnsupportedAtVersionError) as exc_info:
        serialize_for(without_id, V3)
    assert "more" not in str(exc_info.value)  # exactly one underlying error
    assert serialize_for(without_id, V4) == {"method": "notifications/cancelled", "params": {"reason": "bored"}}
    with_id = CancelledNotification(params=CancelledNotificationParams(request_id=7))
    assert serialize_for(with_id, V3) == {"method": "notifications/cancelled", "params": {"requestId": 7}}


# --- subscriptions -----------------------------------------------------------


def test_subscription_filter_extras_survive_emission() -> None:
    """Extensions merge extra keys into the subscription filter on the wire;
    they survive 2026-07-28 emission (spec-mandated open object)."""
    filter_ = SubscriptionFilter.model_validate({"toolsListChanged": True, "taskIds": ["task-1"]})
    request = SubscriptionsListenRequest(
        params=SubscriptionsListenRequestParams(notifications=filter_, _meta=as_meta(identity_meta()))
    )
    out = serialize_for(request, D)
    assert out["params"]["notifications"] == {"toolsListChanged": True, "taskIds": ["task-1"]}


def test_legacy_subscribe_has_no_wire_form_at_2026_07_28() -> None:
    """2026-07-28 removed resources/subscribe (spec-mandated)."""
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(SubscribeRequest(params=SubscribeRequestParams(uri="file:///r")), D)


def test_listen_request_has_no_wire_form_below_2026_07_28() -> None:
    request = SubscriptionsListenRequest(params=SubscriptionsListenRequestParams(notifications=SubscriptionFilter()))
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(request, V4)


def test_initialize_has_no_wire_form_at_2026_07_28() -> None:
    """2026-07-28 removed the initialize handshake; server/discover replaces
    it (spec-mandated)."""
    request = InitializeRequest(
        params=InitializeRequestParams(
            protocol_version=V4, capabilities=ClientCapabilities(), client_info=Implementation(name="c", version="1")
        )
    )
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(request, D)


def test_ping_has_no_wire_form_at_2026_07_28() -> None:
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(PingRequest(), D)


# --- spec-name divergences ----------------------------------------------------


def test_elicit_complete_notification_emits_under_its_schema_name() -> None:
    """The SDK keeps its v1 class name; the schema spells the definition
    'ElicitationCompleteNotification'. Emission resolves through the recorded
    rename and the wire shape is unchanged."""
    notification = ElicitCompleteNotification(params=ElicitCompleteNotificationParams(elicitation_id="e-1"))
    assert serialize_for(notification, V4) == {
        "method": "notifications/elicitation/complete",
        "params": {"elicitationId": "e-1"},
    }


# --- alignment defect guard -----------------------------------------------------


def test_an_invented_redump_key_raises() -> None:
    """A re-validated model emitting a key the original dump never had is
    always a defect in a version package; the alignment walk refuses to emit
    it. Unreachable through the committed packages, so pinned directly."""
    with pytest.raises(RuntimeError, match="invented output keys"):
        _merge_and_align({"a": 1}, {"a": 1, "b": 2})
