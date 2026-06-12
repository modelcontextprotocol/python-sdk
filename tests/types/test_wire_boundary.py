"""Emission facts of `mcp.types.wire.serialize_for`, paired per fact.

The boundary is additive-only: at 2025-11-25 and earlier the emitted body is
the plain model dump, byte-identical (the anchor the v1->v2 compatibility
guarantee pins for existing peers), and at 2026-07-28 the boundary injects
the new protocol's required fields and refuses the values that revision has
no wire form for. Each fact gets a (+) test on the surface that carries it
and a (-) test showing the other surface leaves the dump alone; byte-level
comparisons use `json.dumps` bytes against the plain model dump.
"""

import json
from typing import Any

import pytest
from pydantic import BaseModel, FileUrl

from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    AudioContent,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    CancelTaskRequest,
    CancelTaskRequestParams,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    DiscoverResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    EmptyResult,
    GetTaskRequest,
    GetTaskRequestParams,
    Icon,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
    InputRequiredResult,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsRequest,
    ListRootsResult,
    ListTasksRequest,
    ListToolsRequest,
    ListToolsResult,
    PaginatedRequestParams,
    PingRequest,
    RequestParamsMeta,
    ResourceLink,
    Root,
    RootsCapability,
    RootsListChangedNotification,
    SamplingMessage,
    SamplingMessageContentBlock,
    ServerCapabilities,
    SetLevelRequest,
    SetLevelRequestParams,
    SubscribeRequest,
    SubscribeRequestParams,
    SubscriptionFilter,
    SubscriptionsListenRequest,
    SubscriptionsListenRequestParams,
    TaskMetadata,
    TextContent,
    Tool,
    ToolExecution,
    ToolUseContent,
    UnsubscribeRequest,
    UnsubscribeRequestParams,
)
from mcp.types.wire import UnknownProtocolVersionError, UnsupportedAtVersionError, serialize_for

ALL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")
EARLIER_VERSIONS = ALL_VERSIONS[:-1]

IDENTITY_META: RequestParamsMeta = {
    CLIENT_INFO_META_KEY: {"name": "example-client", "version": "1.0.0"},
    CLIENT_CAPABILITIES_META_KEY: {},
}


def plain_dump(model: BaseModel) -> dict[str, Any]:
    """The user-level dump v2 transports emit; the boundary adds to it, never
    removes from it."""
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def as_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode()


# resultType (spec-mandated: added in 2026-07-28; absent means complete) ------


def test_result_type_injected_as_complete_on_2026_07_28() -> None:
    """Every top-level 2026-07-28 server result carries resultType; an unset
    field emits as "complete"."""
    body = serialize_for(CallToolResult(content=[TextContent(text="hi")]), "2026-07-28")
    assert body["resultType"] == "complete"


def test_input_required_result_injects_its_own_result_type() -> None:
    """An input-required result is its own result type on the 2026-07-28 wire."""
    body = serialize_for(InputRequiredResult(request_state="state"), "2026-07-28")
    assert body["resultType"] == "input_required"


def test_user_set_result_type_is_never_overwritten() -> None:
    """The resultType union is open; a caller-set value (e.g. an extension's) passes through."""
    body = serialize_for(CallToolResult(content=[], result_type="task"), "2026-07-28")
    assert body["resultType"] == "task"


@pytest.mark.parametrize(
    "result",
    [
        CreateMessageResult(role="assistant", content=TextContent(text="ok"), model="m"),
        CreateMessageResultWithTools(role="assistant", content=[TextContent(text="ok")], model="m"),
        ElicitResult(action="accept"),
        ListRootsResult(roots=[Root(uri=FileUrl("file:///w"))]),
    ],
)
def test_result_type_not_injected_into_input_response_payload_types(result: BaseModel) -> None:
    """The 2026-07-28 schema defines no resultType on the sampling, elicitation,
    and roots results: they lost their top-level response frame when the
    revision removed server-to-client requests and survive only as embedded
    input-response payloads. Their emission is the plain dump."""
    assert as_bytes(serialize_for(result, "2026-07-28")) == as_bytes(plain_dump(result))


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_user_set_result_type_passes_through_on_earlier_versions(version: str) -> None:
    """resultType was added in 2026-07-28, but a caller-set value is never
    removed from the dump on older sessions: deployed peers ignore unknown
    keys on non-empty bodies, and silently deleting caller data would
    re-shape the message. The body stays byte-identical to the plain dump."""
    result = CallToolResult(content=[TextContent(text="hi")], result_type="complete")
    assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_unset_fields_keep_an_empty_result_an_empty_object(version: str) -> None:
    """An empty result is exactly {} on 2025-11-25-and-earlier wires by
    construction: every 2026-07-28-only field defaults to None and the dump
    excludes None. Nothing needs removing for strict deployed peers, which
    reject extra keys on EMPTY results specifically."""
    assert as_bytes(serialize_for(EmptyResult(), version)) == b"{}"


def test_user_set_result_type_on_an_empty_result_still_emits() -> None:
    """Even on an otherwise-empty body, a caller-set resultType is emitted —
    the boundary never strips. Strict deployed peers reject such a body;
    the caveat is documented on the `Result.result_type` field, and the
    field's None default keeps normal empty results at {}."""
    assert serialize_for(EmptyResult(result_type="complete"), "2024-11-05") == {"resultType": "complete"}


# Caching fields (spec-mandated: ttlMs/cacheScope required on 2026-07-28
# cacheable results; the fields do not exist earlier) -------------------------


def test_caching_pair_injected_when_unset_on_2026_07_28() -> None:
    """Unset caching fields emit as the don't-cache pair: ttlMs 0, cacheScope private."""
    body = serialize_for(ListToolsResult(tools=[]), "2026-07-28")
    assert body["ttlMs"] == 0
    assert body["cacheScope"] == "private"


def test_user_set_caching_fields_pass_through_unclobbered() -> None:
    """Caller-set caching values are emitted as given."""
    body = serialize_for(ListToolsResult(tools=[], ttl_ms=9000, cache_scope="public"), "2026-07-28")
    assert body["ttlMs"] == 9000
    assert body["cacheScope"] == "public"


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_caching_fields_pass_through_on_earlier_versions(version: str) -> None:
    """ttlMs/cacheScope were added in 2026-07-28; nothing is injected on older
    sessions, and caller-set values are emitted as given (unknown keys are
    wire-safe against deployed peers)."""
    result = ListToolsResult(tools=[], ttl_ms=9000, cache_scope="public")
    assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


# Required request _meta (spec-mandated: every 2026-07-28 request carries the
# reserved protocolVersion/clientInfo/clientCapabilities keys) ----------------


def test_protocol_version_meta_injected_on_2026_07_28_requests() -> None:
    """The protocol version key is boundary-supplied; caller identity keys pass through."""
    request = ListToolsRequest(params=PaginatedRequestParams(_meta={**IDENTITY_META}))
    body = serialize_for(request, "2026-07-28")
    meta = body["params"]["_meta"]
    assert meta[PROTOCOL_VERSION_META_KEY] == "2026-07-28"
    assert meta[CLIENT_INFO_META_KEY] == IDENTITY_META[CLIENT_INFO_META_KEY]
    assert meta[CLIENT_CAPABILITIES_META_KEY] == {}


def test_user_set_protocol_version_meta_is_never_overwritten() -> None:
    """Injection merges: a caller-set protocol version claim survives emission."""
    meta: RequestParamsMeta = {PROTOCOL_VERSION_META_KEY: "2025-11-25", **IDENTITY_META}
    request = ListToolsRequest(params=PaginatedRequestParams(_meta=meta))
    body = serialize_for(request, "2026-07-28")
    assert body["params"]["_meta"][PROTOCOL_VERSION_META_KEY] == "2025-11-25"


def test_request_without_identity_meta_is_refused_on_2026_07_28() -> None:
    """The boundary never synthesizes session identity: a request whose _meta lacks
    the caller-supplied clientInfo/clientCapabilities keys has no legal
    2026-07-28 wire form."""
    with pytest.raises(UnsupportedAtVersionError) as exc_info:
        serialize_for(ListToolsRequest(), "2026-07-28")
    assert exc_info.value.version == "2026-07-28"


def test_request_with_partial_identity_meta_is_refused_on_2026_07_28() -> None:
    """Both identity keys are required; one alone is still refused."""
    meta: RequestParamsMeta = {CLIENT_INFO_META_KEY: {"name": "example-client", "version": "1.0.0"}}
    request = ListToolsRequest(params=PaginatedRequestParams(_meta=meta))
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(request, "2026-07-28")


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_nothing_injected_into_requests_on_earlier_versions(version: str) -> None:
    """Before 2026-07-28 requests carry no reserved _meta keys; unset params stay omitted."""
    body = serialize_for(ListToolsRequest(), version)
    assert as_bytes(body) == as_bytes(plain_dump(ListToolsRequest()))


def test_meta_keys_pass_through_on_earlier_versions() -> None:
    """User-set _meta keys — reserved io.modelcontextprotocol/* names included — are
    never removed on emission.

    Deployed-peer-mandated: open _meta maps are wire-safe against every
    deployed peer, so deleting deliberate caller data would re-shape meaning
    for no benefit.
    """
    meta: RequestParamsMeta = {PROTOCOL_VERSION_META_KEY: "2025-03-26", "example.com/trace": "abc", **IDENTITY_META}
    request = ListToolsRequest(params=PaginatedRequestParams(_meta=meta))
    body = serialize_for(request, "2024-11-05")
    assert as_bytes(body) == as_bytes(plain_dump(request))


# Input-required results (spec-mandated: type added in 2026-07-28; at least
# one of inputRequests/requestState is a schema MUST stated in prose) ---------


def test_input_required_result_with_only_input_requests_is_legal() -> None:
    elicit = ElicitRequest(params=ElicitRequestFormParams(message="m", requested_schema={"type": "object"}))
    body = serialize_for(InputRequiredResult(input_requests={"q1": elicit}), "2026-07-28")
    assert body["resultType"] == "input_required"
    assert "q1" in body["inputRequests"]


def test_input_required_result_with_only_request_state_is_legal() -> None:
    body = serialize_for(InputRequiredResult(request_state="opaque"), "2026-07-28")
    assert body["requestState"] == "opaque"


def test_input_required_result_with_neither_field_is_refused() -> None:
    """An input-required result with neither inputRequests nor requestState has no
    legal wire form; the schema requires at least one of them."""
    with pytest.raises(UnsupportedAtVersionError):
        serialize_for(InputRequiredResult(), "2026-07-28")


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_input_required_result_dumps_plainly_on_earlier_versions(version: str) -> None:
    """The input-required result type was added in 2026-07-28, but whether one
    may be SENT on an older session is the session layer's gate (the result
    shape only exists in the 2026-07-28 flow); the boundary emits the plain
    dump and never blocks."""
    result = InputRequiredResult(request_state="opaque")
    assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


# Payload domain and version registry -----------------------------------------


def test_bare_fragment_raises_type_error() -> None:
    """serialize_for accepts message bodies and envelope models only; fragments are
    shaped in situ, inside the body that carries them."""
    with pytest.raises(TypeError, match="message body or an envelope model"):
        serialize_for(TextContent(text="hi"), "2025-03-26")


def test_bare_fragment_raises_type_error_before_version_lookup() -> None:
    """Argument validation precedes the version lookup: a fragment plus an unknown
    version is a TypeError, deterministically."""
    with pytest.raises(TypeError):
        serialize_for(TextContent(text="hi"), "not-a-version")


def test_unknown_version_serialization_raises() -> None:
    """The type layer never guesses a wire shape for a version it does not know."""
    with pytest.raises(UnknownProtocolVersionError) as exc_info:
        serialize_for(EmptyResult(), "not-a-version")
    assert exc_info.value.version == "not-a-version"
    assert exc_info.value.known[-1] == "2026-07-28"


def test_envelope_models_serialize_verbatim() -> None:
    """Envelope shape is version-invariant: an envelope model dumps exactly as the
    plain model dump on every version, including 2026-07-28."""
    frame = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list")
    for version in ALL_VERSIONS:
        assert as_bytes(serialize_for(frame, version)) == as_bytes(plain_dump(frame))


def test_envelope_result_interior_passes_through_opaque() -> None:
    """A generic envelope's `result` is an untyped dict and is never shaped:
    2026-07-28 keys inside it pass through verbatim even on a 2024-11-05 wire.
    Payload shaping applies when the payload is serialized as its typed model."""
    frame = JSONRPCResponse(jsonrpc="2.0", id=1, result={"resultType": "complete", "ttlMs": 5})
    assert as_bytes(serialize_for(frame, "2024-11-05")) == as_bytes(plain_dump(frame))


# 2026-07-28 type floor (spec-mandated: the revision removed the initialize
# handshake, ping, logging/setLevel, the per-URI resources subscribe pair, the
# roots list_changed notification, and the 2025-11-25 task types) -------------

REMOVED_AT_2026_07_28 = (
    InitializeRequest(
        params=InitializeRequestParams(
            protocol_version="2025-11-25",
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="example-client", version="1.0.0"),
        )
    ),
    InitializeResult(
        protocol_version="2025-11-25",
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="example-server", version="1.0.0"),
    ),
    InitializedNotification(),
    PingRequest(),
    SetLevelRequest(params=SetLevelRequestParams(level="info")),
    SubscribeRequest(params=SubscribeRequestParams(uri="file:///r.txt")),
    UnsubscribeRequest(params=UnsubscribeRequestParams(uri="file:///r.txt")),
    RootsListChangedNotification(),
    GetTaskRequest(params=GetTaskRequestParams(task_id="t1")),
    CancelTaskRequest(params=CancelTaskRequestParams(task_id="t1")),
    ListTasksRequest(),
)


@pytest.mark.parametrize("model", REMOVED_AT_2026_07_28, ids=lambda model: type(model).__name__)
def test_removed_types_have_no_2026_07_28_wire_form(model: BaseModel) -> None:
    """A value whose type the 2026-07-28 schema does not define cannot be
    emitted to a 2026-07-28 peer; emission refuses loudly instead of
    guessing a shape."""
    with pytest.raises(UnsupportedAtVersionError) as exc_info:
        serialize_for(model, "2026-07-28")
    assert exc_info.value.version == "2026-07-28"


@pytest.mark.parametrize("model", REMOVED_AT_2026_07_28, ids=lambda model: type(model).__name__)
@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_removed_types_dump_plainly_on_earlier_versions(version: str, model: BaseModel) -> None:
    """The same bodies emit as the plain dump on every 2025-11-25-and-earlier
    session — including versions that predate a construct (the 2025-11-25
    task types on a 2024-11-05 wire): whether a peer can handle a newer
    method is the session layer's dispatch gate, not an emission rule."""
    assert as_bytes(serialize_for(model, version)) == as_bytes(plain_dump(model))


# Sampling content (spec-mandated: tool_use/tool_result and array content
# joined the sampling content union in 2025-11-25) -----------------------------


def sampling_request(content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]) -> CreateMessageRequest:
    params = CreateMessageRequestParams(messages=[SamplingMessage(role="user", content=content)], max_tokens=10)
    return CreateMessageRequest(params=params)


TOOL_USE_BLOCK = ToolUseContent(name="lookup", id="call-1", input={})


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_tool_sampling_content_emits_plainly_at_every_earlier_version(version: str) -> None:
    """Tool content joined the sampling union in 2025-11-25, and deployed peers
    reject unknown union TAGS — but whether the negotiated session admits it
    (the sampling.tools capability) is a session-layer gate. The boundary
    emits the plain dump at every version, request and result side alike."""
    request = sampling_request(TOOL_USE_BLOCK)
    result = CreateMessageResultWithTools(role="assistant", content=[TOOL_USE_BLOCK], model="m")
    assert as_bytes(serialize_for(request, version)) == as_bytes(plain_dump(request))
    assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_array_sampling_content_emits_plainly_at_every_earlier_version(version: str) -> None:
    """Array message content arrived with sampling tools in 2025-11-25; through
    2025-06-18 the schemas type content as a single block. Single-block peers
    are a session-layer concern: emission never reshapes or blocks an array."""
    request = sampling_request([TextContent(text="a"), TextContent(text="b")])
    result = CreateMessageResultWithTools(role="assistant", content=[TextContent(text="a")], model="m")
    assert as_bytes(serialize_for(request, version)) == as_bytes(plain_dump(request))
    assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


def test_single_block_sampling_content_emitted_on_earlier_versions() -> None:
    """A single text/image/audio block is the shape every version supports; both
    carriers emit byte-identical to the plain dump."""
    request = sampling_request(TextContent(text="hi"))
    result = CreateMessageResultWithTools(role="assistant", content=TextContent(text="ok"), model="m")
    assert as_bytes(serialize_for(request, "2024-11-05")) == as_bytes(plain_dump(request))
    assert as_bytes(serialize_for(result, "2024-11-05")) == as_bytes(plain_dump(result))


# Elicitation modes and values (spec-mandated: url mode and multi-select list
# values were added in 2025-11-25) --------------------------------------------

URL_PARAMS = ElicitRequestURLParams(message="sign in", url="https://example.com/auth", elicitation_id="e1")


@pytest.mark.parametrize("version", ALL_VERSIONS[:-1])
def test_url_mode_elicitation_emits_plainly_at_every_earlier_version(version: str) -> None:
    """Url-mode elicitation params were added in 2025-11-25 (gated on a live
    session by the elicitation.url capability — a session-layer concern);
    emission is the plain dump at every version."""
    request = ElicitRequest(params=URL_PARAMS)
    assert as_bytes(serialize_for(request, version)) == as_bytes(plain_dump(request))


def test_form_mode_elicitation_emitted_on_earlier_versions() -> None:
    """Form mode is the original elicitation shape and emits unchanged."""
    request = ElicitRequest(params=ElicitRequestFormParams(message="m", requested_schema={"type": "object"}))
    assert as_bytes(serialize_for(request, "2025-06-18")) == as_bytes(plain_dump(request))


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_multi_select_elicit_values_emit_plainly_at_every_earlier_version(version: str) -> None:
    """List-valued elicitation content (multi-select) was added in 2025-11-25;
    older sessions emit the caller's values verbatim all the same."""
    result = ElicitResult(action="accept", content={"langs": ["en", "fr"]})
    assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


@pytest.mark.parametrize("version", ALL_VERSIONS[2:])
def test_null_elicit_content_values_pass_through_at_every_modeled_version(version: str) -> None:
    """No schema version types a null elicitation answer — the monolith's
    None value arm exists for v1.x constructor compatibility — but emitted
    values are caller data and travel verbatim at every version that models
    elicitation, exactly as python v1.x itself constructs, accepts, and
    emits the same body (deployed-peer-mandated pass-through; a version's
    narrower value typing decides parses, never emissions)."""
    result = ElicitResult(action="accept", content={"x": None, "y": "ok"})
    out = serialize_for(result, version)
    assert out["content"] == {"x": None, "y": "ok"}
    assert as_bytes(out) == as_bytes(plain_dump(result))


def test_scalar_elicit_values_emitted_on_earlier_versions() -> None:
    """Scalar elicitation values — and a content-less decline — are legal at every
    version and emit byte-identical to the plain dump."""
    accepted = ElicitResult(action="accept", content={"name": "x", "count": 2})
    declined = ElicitResult(action="decline")
    assert as_bytes(serialize_for(accepted, "2024-11-05")) == as_bytes(plain_dump(accepted))
    assert as_bytes(serialize_for(declined, "2024-11-05")) == as_bytes(plain_dump(declined))


# Cancellation requestId (spec-mandated: required on the wire through
# 2025-06-18, optional from 2025-11-25) ---------------------------------------


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_cancellation_without_request_id_emits_at_every_version(version: str) -> None:
    """requestId is required on the wire through 2025-06-18 and optional from
    2025-11-25; supplying it on the older sessions is the caller's
    obligation — the boundary emits what the caller built, on every version."""
    notification = CancelledNotification(params=CancelledNotificationParams(reason="done"))
    assert as_bytes(serialize_for(notification, version)) == as_bytes(plain_dump(notification))


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_cancellation_with_request_id_emitted_at_every_version(version: str) -> None:
    notification = CancelledNotification(params=CancelledNotificationParams(request_id=7))
    assert as_bytes(serialize_for(notification, version)) == as_bytes(plain_dump(notification))


# Task metadata (spec-mandated: the params `task` field exists on the
# 2025-11-25 wire only) ---------------------------------------------------------


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_task_metadata_emits_at_every_earlier_version(version: str) -> None:
    """The params task field exists on the 2025-11-25 wire only, but a caller-set
    value is never removed: versions that predate it ignore the unknown key,
    and targeting the field at the right session is session-layer work."""
    request = CallToolRequest(params=CallToolRequestParams(name="t", task=TaskMetadata(ttl=5000)))
    body = serialize_for(request, version)
    assert body["params"]["task"] == {"ttl": 5000}
    assert as_bytes(body) == as_bytes(plain_dump(request))


def test_task_metadata_emits_on_2026_07_28() -> None:
    """2026-07-28 removed request-side task metadata from the schema (tasks
    continue as an extension), but field-level extras never fail the strict
    surface: the caller's value emits alongside the injected _meta keys."""
    params = CallToolRequestParams(name="t", task=TaskMetadata(ttl=5000), _meta={**IDENTITY_META})
    body = serialize_for(CallToolRequest(params=params), "2026-07-28")
    assert body["params"]["task"] == {"ttl": 5000}


# Capabilities subtrees (spec-mandated: the `tasks` subtree exists on the
# 2025-11-25 wire only; `extensions` was added in 2026-07-28; the roots
# capability's listChanged flag was removed in 2026-07-28) ---------------------


def initialize_request(capabilities: ClientCapabilities) -> InitializeRequest:
    params = InitializeRequestParams(
        protocol_version="2025-11-25",
        capabilities=capabilities,
        client_info=Implementation(name="example-client", version="1.0.0"),
    )
    return InitializeRequest(params=params)


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_tasks_capability_emits_at_every_earlier_version(version: str) -> None:
    """The capabilities tasks subtree is a 2025-11-25 schema fact, but a set
    subtree emits on every earlier version too: unknown capability keys are
    wire-safe against deployed peers."""
    request = initialize_request(ClientCapabilities.model_validate({"tasks": {}}))
    body = serialize_for(request, version)
    assert body["params"]["capabilities"] == {"tasks": {}}
    assert as_bytes(body) == as_bytes(plain_dump(request))


def test_tasks_capability_emits_on_2026_07_28_server_capabilities() -> None:
    """A 2026-07-28 discover result advertises capability extensions; a set
    2025-11-25-only tasks subtree on the same object emits too (field-level
    extras never fail the strict surface)."""
    result = DiscoverResult(
        supported_versions=["2026-07-28"],
        capabilities=ServerCapabilities.model_validate({"extensions": {"example.com/cap": {}}, "tasks": {}}),
        server_info=Implementation(name="example-server", version="1.0.0"),
    )
    body = serialize_for(result, "2026-07-28")
    assert body["capabilities"] == {"extensions": {"example.com/cap": {}}, "tasks": {}}


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_extensions_capability_emits_at_every_earlier_version(version: str) -> None:
    """The extensions field was added in 2026-07-28; a caller-set value emits on
    every earlier version unchanged (unknown capability keys are wire-safe)."""
    request = initialize_request(ClientCapabilities(extensions={"example.com/cap": {}}))
    body = serialize_for(request, version)
    assert body["params"]["capabilities"] == {"extensions": {"example.com/cap": {}}}
    assert as_bytes(body) == as_bytes(plain_dump(request))


def test_roots_list_changed_meta_projection_passes_through_on_2026_07_28() -> None:
    """2026-07-28 removed the roots capability's listChanged flag from the
    schema, but the boundary never reaches inside _meta values: a client
    capabilities projection carrying it (the per-request `_meta` shape a
    session emits) travels verbatim."""
    meta: RequestParamsMeta = {
        CLIENT_INFO_META_KEY: {"name": "example-client", "version": "1.0.0"},
        CLIENT_CAPABILITIES_META_KEY: {"roots": {"listChanged": True}},
    }
    request = ListToolsRequest(params=PaginatedRequestParams(_meta=meta))
    body = serialize_for(request, "2026-07-28")
    assert body["params"]["_meta"][CLIENT_CAPABILITIES_META_KEY] == {"roots": {"listChanged": True}}


# Lifecycle bodies (spec-mandated shapes through 2025-11-25; byte-identity is
# the compatibility anchor for existing peers) ---------------------------------


@pytest.mark.parametrize("version", EARLIER_VERSIONS)
def test_lifecycle_bodies_byte_identical_through_2025_11_25(version: str) -> None:
    bodies = (
        initialize_request(ClientCapabilities(roots=RootsCapability(list_changed=True))),
        InitializeResult(
            protocol_version=version,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="example-server", version="1.0.0"),
            instructions="hello",
        ),
        InitializedNotification(),
        PingRequest(),
    )
    for body in bodies:
        assert as_bytes(serialize_for(body, version)) == as_bytes(plain_dump(body))


# Pass-through (deployed-peer-mandated: new optional fields on known types are
# wire-safe, and values are never narrowed on emission) ------------------------


def test_newer_tool_fields_and_opened_schemas_pass_through_at_every_version() -> None:
    """Opened 2020-12 schemas pass through unchanged, and newer optional fields
    (title, icons) survive old-version emission: stripping them would break
    byte-identity for values plain v2 constructors accept."""
    tool = Tool(
        name="t",
        title="Tool",
        icons=[Icon(src="https://example.com/i.png")],
        input_schema={"type": ["object", "null"]},
        output_schema={"anyOf": [{"type": "string"}, {"type": "null"}]},
    )
    result = ListToolsResult(tools=[tool])
    for version in EARLIER_VERSIONS:
        assert as_bytes(serialize_for(result, version)) == as_bytes(plain_dump(result))


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_tool_execution_passes_through_at_every_version(version: str) -> None:
    """`Tool.execution` exists only in the 2025-11-25 schema, but it describes
    the tool rather than directing protocol machinery, so no version removes a
    set value — not even 2026-07-28, which removed the field."""
    tool = Tool(name="t", input_schema={"type": "object"}, execution=ToolExecution(task_support="optional"))
    body = serialize_for(ListToolsResult(tools=[tool]), version)
    assert body["tools"][0]["execution"] == {"taskSupport": "optional"}


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_scalar_structured_content_passes_at_every_version(version: str) -> None:
    """structuredContent values are never narrowed on emission; 2026-07-28 opened
    the field to any JSON value and older emission passes user data through."""
    body = serialize_for(CallToolResult(content=[], structured_content=5), version)
    assert body["structuredContent"] == 5


def test_audio_and_resource_link_content_not_gated_on_emission() -> None:
    """audio (added 2025-03-26) and resource_link (added 2025-06-18) content
    blocks are deliberately not version-gated on emission: sibling SDKs emit
    them ungated, and a peer that predates them rejects at request level."""
    result = CallToolResult(
        content=[
            AudioContent(data="UklGRg==", mime_type="audio/wav"),
            ResourceLink(name="r", uri="file:///r.txt"),
        ]
    )
    assert as_bytes(serialize_for(result, "2024-11-05")) == as_bytes(plain_dump(result))


# Embedded payloads (spec-mandated 2026-07-28 multi-round-trip flow; the
# boundary never recurses into an embedded message body) -----------------------


def test_no_meta_injected_into_embedded_input_requests() -> None:
    """Embedded input-request payloads are not JSON-RPC requests on the wire:
    no params or reserved _meta keys are materialized inside them."""
    body = serialize_for(InputRequiredResult(input_requests={"r1": ListRootsRequest()}), "2026-07-28")
    assert body["resultType"] == "input_required"
    assert body["inputRequests"]["r1"] == {"method": "roots/list"}


def test_embedded_input_responses_pass_through_verbatim_on_2026_07_28() -> None:
    """Injections apply to the top-level result only: an embedded response value
    keeps a user-set resultType and never gains one it does not carry."""
    params = CallToolRequestParams(
        name="t",
        input_responses={
            "r1": ElicitResult(action="accept", result_type="custom"),
            "r2": ElicitResult(action="decline"),
        },
        request_state="opaque",
        _meta={**IDENTITY_META},
    )
    body = serialize_for(CallToolRequest(params=params), "2026-07-28")
    responses = body["params"]["inputResponses"]
    assert responses["r1"]["resultType"] == "custom"
    assert "resultType" not in responses["r2"]


def test_embedded_response_values_emit_verbatim_on_earlier_versions() -> None:
    """Embedded message bodies pass through verbatim on every version — an
    embedded response value keeps its user-set fields exactly as built."""
    params = CallToolRequestParams(
        name="t", input_responses={"r1": ElicitResult(action="accept", result_type="custom")}
    )
    request = CallToolRequest(params=params)
    assert as_bytes(serialize_for(request, "2024-11-05")) == as_bytes(plain_dump(request))


# Subscription filters (spec-mandated: extensions merge additional keys into
# the filter object on the wire) ------------------------------------------------


def test_subscription_filter_extension_keys_survive_emission() -> None:
    listen_filter = SubscriptionFilter.model_validate({"toolsListChanged": True, "taskIds": ["t1"]})
    params = SubscriptionsListenRequestParams(notifications=listen_filter, _meta={**IDENTITY_META})
    body = serialize_for(SubscriptionsListenRequest(params=params), "2026-07-28")
    assert body["params"]["notifications"]["taskIds"] == ["t1"]
    assert body["params"]["notifications"]["toolsListChanged"] is True
