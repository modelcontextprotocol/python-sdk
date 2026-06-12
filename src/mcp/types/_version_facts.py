"""Per-version wire facts for the MCP type layer.

One literal `VersionFacts` block per protocol version, oldest to newest. Each
block states everything the type layer knows about that version's wire in one
place: which methods exist in each direction, plus the version's emission
shaping rows (fields dropped because the version predates them, required
fields injected when unset, values with no legal wire form). Shaping rows are
sparse by design — a field carried by no row in any block is emitted verbatim
at every version; `Strip`'s docstring states the dividing line. Facts are
deliberately repeated across blocks instead of factored into shared constants,
so a version's behavior can be read top to bottom without resolving anything
else; `tests/types/test_version_facts_oracle.py` re-derives every
schema-expressible fact from the generated spec oracles, so drift between
blocks is caught mechanically.

This module is data plus the small named predicates the `Refuse` rows point
at: the row dataclasses define the fact vocabulary, the predicates state the
value conditions some rows carry, and the blocks are literals. The engine that
interprets the rows lives in `mcp.types._shaping`; the public entry points
live in `mcp.types.wire`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel

from mcp.types._types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    CacheableResult,
    CallToolRequestParams,
    CancelledNotification,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResultWithTools,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    InputRequiredResult,
    Result,
    RootsCapability,
    SamplingMessageContentBlock,
    ServerCapabilities,
    ToolResultContent,
    ToolUseContent,
)


class UnsupportedAtVersionError(ValueError):
    """The value cannot be legally represented on this version's wire.

    Raised on serialization instead of silently dropping or re-shaping a value
    in a way that would change its meaning for the receiving peer. Triggered
    by the `Refuse` rows below and by the required-`_meta` check on 2026-07-28
    requests; defined here so both the engine and the boundary can raise it,
    and re-exported by `mcp.types.wire` as part of the public surface.
    """

    def __init__(self, version: str, message: str) -> None:
        super().__init__(message)
        self.version: str = version


@dataclass(frozen=True)
class Strip:
    """This wire field does not exist at this version: serialization drops it
    even when user-set.

    Not every field a version's schema lacks gets a row, and the absence of a
    row is itself a ruling: a field no block names is emitted verbatim at
    every version. A field gets rows only when it directs the peer's protocol
    machinery — result typing and caching directives, capability
    advertisements, request task metadata — where dropping it on a version
    without that machinery loses nothing the message meant. Fields that
    merely describe the object carrying them (`Tool.execution`, `icons`,
    `title`, ...) pass through instead: deployed peers ignore object fields
    they do not recognize, while silently deleting a caller-set value would
    re-shape the message the caller built. Where dropping a value would
    change the message's meaning, the version gets a `Refuse` row, never a
    quiet strip.
    """

    owner: type[BaseModel]
    """Model the rule applies to; matched by isinstance, so base classes fan out."""

    wire_field: str
    """The camelCase wire key to drop."""


@dataclass(frozen=True)
class Inject:
    """This version's wire requires the field: set `value` when the dump lacks
    the key.

    Inject-if-absent — never clobbers a user-set value, and applies to the
    top-level model only (never recurses into embedded payloads).
    """

    owner: type[BaseModel]
    """Model the rule applies to; matched by isinstance, so base classes fan out."""

    wire_field: str
    """The camelCase wire key to set."""

    value: object
    """A JSON literal; no symbolic value sources."""


@dataclass(frozen=True)
class Refuse:
    """The value has no legal wire form at this version: serialization raises
    `UnsupportedAtVersionError`."""

    owner: type[BaseModel]
    """Model the rule applies to; matched by isinstance, so base classes fan out."""

    when: Callable[[Any], bool] | None
    """None = the type itself is refused; else a named predicate defined above
    the blocks."""

    because: str
    """Exception message fragment naming the construct that cannot be sent."""


@dataclass(frozen=True)
class VersionFacts:
    """Everything the type layer knows about one protocol version's wire."""

    version: str
    client_request_methods: frozenset[str]
    client_notification_methods: frozenset[str]
    server_request_methods: frozenset[str]
    server_notification_methods: frozenset[str]
    strip_on_emit: tuple[Strip, ...]
    inject_on_emit: tuple[Inject, ...]
    refuse_on_emit: tuple[Refuse, ...]
    meta_required_methods: frozenset[str]
    """Methods whose request params `_meta` must carry the reserved
    io.modelcontextprotocol keys (protocolVersion, clientInfo,
    clientCapabilities): on emission the container is materialized and
    protocolVersion injected; on parse all three keys are required."""

    recognized_result_types: frozenset[str]
    """Accepted `resultType` values on parse; empty = no mandate (any value
    parses at this version)."""


# ----------------------------------------------------------------------------
# Named predicates for the `Refuse` rows that condition on a value, not just a
# type. Each one states a single wire fact checkable against the pinned public
# schemas; none contains version logic — the block a row sits in is the only
# version scope.
# ----------------------------------------------------------------------------


def _sampling_content_blocks(
    model: CreateMessageRequest | CreateMessageResultWithTools,
) -> list[SamplingMessageContentBlock]:
    """Every content block a sampling carrier holds, flattened.

    `CreateMessageRequest` carries blocks in `params.messages[*].content`;
    `CreateMessageResultWithTools` carries its own `content`. Either spot
    holds a single block or a list of blocks.
    """
    if isinstance(model, CreateMessageRequest):
        contents = [message.content for message in model.params.messages]
    else:
        contents = [model.content]
    blocks: list[SamplingMessageContentBlock] = []
    for content in contents:
        if isinstance(content, list):
            blocks.extend(content)
        else:
            blocks.append(content)
    return blocks


def _sampling_tool_content(model: CreateMessageRequest | CreateMessageResultWithTools) -> bool:
    """Any sampling content block is tool_use/tool_result content.

    Tool content joined the sampling content union in 2025-11-25; earlier
    versions have no wire form for it.
    """
    return any(isinstance(block, ToolUseContent | ToolResultContent) for block in _sampling_content_blocks(model))


def _sampling_array_content(model: CreateMessageRequest | CreateMessageResultWithTools) -> bool:
    """Sampling message content is an array of blocks.

    Array content arrived with sampling tool support in 2025-11-25; through
    2025-06-18 every schema types message content as a single block, and an
    array cannot be collapsed to one block without changing meaning.
    """
    if isinstance(model, CreateMessageRequest):
        return any(isinstance(message.content, list) for message in model.params.messages)
    return isinstance(model.content, list)


def _elicit_url_mode_params(model: ElicitRequest) -> bool:
    """The elicitation request carries url-mode params (mode added in 2025-11-25)."""
    return isinstance(model.params, ElicitRequestURLParams)


def _elicit_list_values(model: ElicitResult) -> bool:
    """Any submitted elicitation value is a list (multi-select, added in 2025-11-25)."""
    return model.content is not None and any(isinstance(value, list) for value in model.content.values())


def _missing_request_id(model: CancelledNotification) -> bool:
    """The cancellation names no request id (`requestId` is required through 2025-06-18)."""
    return model.params.request_id is None


def _empty_input_required(model: InputRequiredResult) -> bool:
    """Neither `inputRequests` nor `requestState` is set.

    The 2026-07-28 schema types both fields as optional but requires at least
    one of them in prose, so the check lives at emission; inbound parsing
    stays lenient.
    """
    return model.input_requests is None and model.request_state is None


def missing_identity_meta(model: Any) -> bool:
    """The request's `params._meta` lacks a caller-supplied identity key.

    The 2026-07-28 schema requires `io.modelcontextprotocol/clientInfo` and
    `io.modelcontextprotocol/clientCapabilities` on every request `_meta`. The
    wire boundary injects only `io.modelcontextprotocol/protocolVersion` and
    never synthesizes session identity, so the caller (normally the session
    layer) must supply both keys before emission. Consumed by the engine's
    required-`_meta` step, not by a `Refuse` row — which methods it applies to
    is the `meta_required_methods` scalar of each block — hence the only
    predicate here without a leading underscore: it crosses a module boundary.
    """
    params = model.params
    meta = params.meta if params is not None else None
    return meta is None or CLIENT_INFO_META_KEY not in meta or CLIENT_CAPABILITIES_META_KEY not in meta


# ============================================================================
# 2024-11-05
# Pinned schema: schema/2024-11-05/schema.ts @ 6d441518
# (github.com/modelcontextprotocol/modelcontextprotocol).
# Verified against the generated oracle tests/spec_oracles/v2024_11_05.py by
# tests/types/test_version_facts_oracle.py.
# ============================================================================
V2024_11_05 = VersionFacts(
    version="2024-11-05",
    client_request_methods=frozenset(
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
    client_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/initialized",
            "notifications/progress",
            "notifications/roots/list_changed",
        }
    ),
    server_request_methods=frozenset(
        {
            "ping",
            "roots/list",
            "sampling/createMessage",
        }
    ),
    server_notification_methods=frozenset(
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
    strip_on_emit=(
        Strip(Result, "resultType"),  # added in 2026-07-28
        Strip(CacheableResult, "ttlMs"),  # added in 2026-07-28
        Strip(CacheableResult, "cacheScope"),  # added in 2026-07-28
        Strip(ClientCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ServerCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ClientCapabilities, "tasks"),  # 2025-11-25 only
        Strip(ServerCapabilities, "tasks"),  # 2025-11-25 only
        Strip(CallToolRequestParams, "task"),  # 2025-11-25 only
        Strip(CreateMessageRequestParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestFormParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestURLParams, "task"),  # 2025-11-25 only
    ),
    # Nothing is injected before 2026-07-28; unset fields stay omitted, so a
    # model that sets none of the fields stripped above dumps byte-identical
    # to the plain model dump.
    inject_on_emit=(),
    refuse_on_emit=(
        # The input-required result type was added in 2026-07-28.
        Refuse(InputRequiredResult, None, "input-required results"),
        # Tool content joined the sampling content union in 2025-11-25.
        Refuse(CreateMessageRequest, _sampling_tool_content, "tool_use/tool_result sampling content"),
        Refuse(CreateMessageResultWithTools, _sampling_tool_content, "tool_use/tool_result sampling content"),
        # Array sampling content arrived with sampling tools in 2025-11-25;
        # message content is a single block at this version.
        Refuse(CreateMessageRequest, _sampling_array_content, "array sampling content"),
        Refuse(CreateMessageResultWithTools, _sampling_array_content, "array sampling content"),
        # Url-mode elicitation params were added in 2025-11-25.
        Refuse(ElicitRequest, _elicit_url_mode_params, "url-mode elicitation"),
        # Multi-select (list) elicitation values were added in 2025-11-25.
        Refuse(ElicitResult, _elicit_list_values, "multi-select elicitation values"),
        # requestId is required on this version's wire; 2025-11-25 made it optional.
        Refuse(CancelledNotification, _missing_request_id, "cancellation without requestId"),
    ),
    meta_required_methods=frozenset(),
    recognized_result_types=frozenset(),
)


# ============================================================================
# 2025-03-26
# Pinned schema: schema/2025-03-26/schema.ts @ 6d441518
# (github.com/modelcontextprotocol/modelcontextprotocol).
# Verified against the generated oracle tests/spec_oracles/v2025_03_26.py by
# tests/types/test_version_facts_oracle.py.
# ============================================================================
V2025_03_26 = VersionFacts(
    version="2025-03-26",
    client_request_methods=frozenset(
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
    client_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/initialized",
            "notifications/progress",
            "notifications/roots/list_changed",
        }
    ),
    server_request_methods=frozenset(
        {
            "ping",
            "roots/list",
            "sampling/createMessage",
        }
    ),
    server_notification_methods=frozenset(
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
    strip_on_emit=(
        Strip(Result, "resultType"),  # added in 2026-07-28
        Strip(CacheableResult, "ttlMs"),  # added in 2026-07-28
        Strip(CacheableResult, "cacheScope"),  # added in 2026-07-28
        Strip(ClientCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ServerCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ClientCapabilities, "tasks"),  # 2025-11-25 only
        Strip(ServerCapabilities, "tasks"),  # 2025-11-25 only
        Strip(CallToolRequestParams, "task"),  # 2025-11-25 only
        Strip(CreateMessageRequestParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestFormParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestURLParams, "task"),  # 2025-11-25 only
    ),
    # Nothing is injected before 2026-07-28; unset fields stay omitted, so a
    # model that sets none of the fields stripped above dumps byte-identical
    # to the plain model dump.
    inject_on_emit=(),
    refuse_on_emit=(
        # The input-required result type was added in 2026-07-28.
        Refuse(InputRequiredResult, None, "input-required results"),
        # Tool content joined the sampling content union in 2025-11-25.
        Refuse(CreateMessageRequest, _sampling_tool_content, "tool_use/tool_result sampling content"),
        Refuse(CreateMessageResultWithTools, _sampling_tool_content, "tool_use/tool_result sampling content"),
        # Array sampling content arrived with sampling tools in 2025-11-25;
        # message content is a single block at this version.
        Refuse(CreateMessageRequest, _sampling_array_content, "array sampling content"),
        Refuse(CreateMessageResultWithTools, _sampling_array_content, "array sampling content"),
        # Url-mode elicitation params were added in 2025-11-25.
        Refuse(ElicitRequest, _elicit_url_mode_params, "url-mode elicitation"),
        # Multi-select (list) elicitation values were added in 2025-11-25.
        Refuse(ElicitResult, _elicit_list_values, "multi-select elicitation values"),
        # requestId is required on this version's wire; 2025-11-25 made it optional.
        Refuse(CancelledNotification, _missing_request_id, "cancellation without requestId"),
    ),
    meta_required_methods=frozenset(),
    recognized_result_types=frozenset(),
)


# ============================================================================
# 2025-06-18
# Pinned schema: schema/2025-06-18/schema.ts @ 6d441518
# (github.com/modelcontextprotocol/modelcontextprotocol).
# Verified against the generated oracle tests/spec_oracles/v2025_06_18.py by
# tests/types/test_version_facts_oracle.py.
# ============================================================================
V2025_06_18 = VersionFacts(
    version="2025-06-18",
    client_request_methods=frozenset(
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
    client_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/initialized",
            "notifications/progress",
            "notifications/roots/list_changed",
        }
    ),
    server_request_methods=frozenset(
        {
            "elicitation/create",  # added in 2025-06-18
            "ping",
            "roots/list",
            "sampling/createMessage",
        }
    ),
    server_notification_methods=frozenset(
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
    strip_on_emit=(
        Strip(Result, "resultType"),  # added in 2026-07-28
        Strip(CacheableResult, "ttlMs"),  # added in 2026-07-28
        Strip(CacheableResult, "cacheScope"),  # added in 2026-07-28
        Strip(ClientCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ServerCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ClientCapabilities, "tasks"),  # 2025-11-25 only
        Strip(ServerCapabilities, "tasks"),  # 2025-11-25 only
        Strip(CallToolRequestParams, "task"),  # 2025-11-25 only
        Strip(CreateMessageRequestParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestFormParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestURLParams, "task"),  # 2025-11-25 only
    ),
    # Nothing is injected before 2026-07-28; unset fields stay omitted, so a
    # model that sets none of the fields stripped above dumps byte-identical
    # to the plain model dump.
    inject_on_emit=(),
    refuse_on_emit=(
        # The input-required result type was added in 2026-07-28.
        Refuse(InputRequiredResult, None, "input-required results"),
        # Tool content joined the sampling content union in 2025-11-25.
        Refuse(CreateMessageRequest, _sampling_tool_content, "tool_use/tool_result sampling content"),
        Refuse(CreateMessageResultWithTools, _sampling_tool_content, "tool_use/tool_result sampling content"),
        # Array sampling content arrived with sampling tools in 2025-11-25;
        # message content is a single block at this version.
        Refuse(CreateMessageRequest, _sampling_array_content, "array sampling content"),
        Refuse(CreateMessageResultWithTools, _sampling_array_content, "array sampling content"),
        # Url-mode elicitation params were added in 2025-11-25.
        Refuse(ElicitRequest, _elicit_url_mode_params, "url-mode elicitation"),
        # Multi-select (list) elicitation values were added in 2025-11-25.
        Refuse(ElicitResult, _elicit_list_values, "multi-select elicitation values"),
        # requestId is required on this version's wire; 2025-11-25 made it optional.
        Refuse(CancelledNotification, _missing_request_id, "cancellation without requestId"),
    ),
    meta_required_methods=frozenset(),
    recognized_result_types=frozenset(),
)


# ============================================================================
# 2025-11-25
# Pinned schema: schema/2025-11-25/schema.ts @ 6d441518
# (github.com/modelcontextprotocol/modelcontextprotocol).
# Verified against the generated oracle tests/spec_oracles/v2025_11_25.py by
# tests/types/test_version_facts_oracle.py.
#
# The 2025-11-25 schema also defines four task request methods (tasks/cancel,
# tasks/get, tasks/list, tasks/result) in both request directions. They are
# deliberately absent from these tables: this SDK models the task payload
# types for compatibility but never dispatches the methods (tasks continue as
# an extension). notifications/tasks/status stays: it is a method fact of the
# 2025-11-25 schema, and the tables classify methods regardless of whether
# the SDK's unions carry the payload type.
# ============================================================================
V2025_11_25 = VersionFacts(
    version="2025-11-25",
    client_request_methods=frozenset(
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
    client_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/initialized",
            "notifications/progress",
            "notifications/roots/list_changed",
            "notifications/tasks/status",  # added in 2025-11-25
        }
    ),
    server_request_methods=frozenset(
        {
            "elicitation/create",
            "ping",
            "roots/list",
            "sampling/createMessage",
        }
    ),
    server_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/elicitation/complete",  # added in 2025-11-25
            "notifications/message",
            "notifications/progress",
            "notifications/prompts/list_changed",
            "notifications/resources/list_changed",
            "notifications/resources/updated",
            "notifications/tasks/status",  # added in 2025-11-25
            "notifications/tools/list_changed",
        }
    ),
    strip_on_emit=(
        Strip(Result, "resultType"),  # added in 2026-07-28
        Strip(CacheableResult, "ttlMs"),  # added in 2026-07-28
        Strip(CacheableResult, "cacheScope"),  # added in 2026-07-28
        Strip(ClientCapabilities, "extensions"),  # added in 2026-07-28
        Strip(ServerCapabilities, "extensions"),  # added in 2026-07-28
        # No task rows: 2025-11-25 is the one version whose wire carries the
        # capabilities `tasks` subtrees and the params `task` field.
    ),
    # Nothing is injected before 2026-07-28; unset fields stay omitted, so a
    # model that sets none of the fields stripped above dumps byte-identical
    # to the plain model dump.
    inject_on_emit=(),
    refuse_on_emit=(
        # The input-required result type was added in 2026-07-28. This is the
        # only refusal here: the 2025-11-25 schema admits tool and array
        # sampling content, url-mode elicitation, multi-select elicitation
        # values, and an absent cancellation requestId.
        Refuse(InputRequiredResult, None, "input-required results"),
    ),
    meta_required_methods=frozenset(),
    recognized_result_types=frozenset(),
)


# ============================================================================
# 2026-07-28
# Pinned schema: schema/draft/schema.ts @ 6d441518, protocol revision
# 2026-07-28 (github.com/modelcontextprotocol/modelcontextprotocol).
# Verified against the generated oracle tests/spec_oracles/v2026_07_28.py by
# tests/types/test_version_facts_oracle.py.
#
# 2026-07-28 removes the initialize handshake (replaced by server/discover
# plus per-request `_meta`), logging/setLevel, the resources subscribe and
# unsubscribe pair (replaced by subscriptions/listen), ping, and the entire
# standalone server-to-client request channel (sampling, roots, and
# elicitation requests become payloads embedded in input-required results).
# ============================================================================
V2026_07_28 = VersionFacts(
    version="2026-07-28",
    client_request_methods=frozenset(
        {
            "completion/complete",
            "prompts/get",
            "prompts/list",
            "resources/list",
            "resources/read",
            "resources/templates/list",
            "server/discover",  # added in 2026-07-28
            "subscriptions/listen",  # added in 2026-07-28
            "tools/call",
            "tools/list",
        }
    ),
    client_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/progress",
        }
    ),
    server_request_methods=frozenset(),  # 2026-07-28 removed server-to-client requests
    server_notification_methods=frozenset(
        {
            "notifications/cancelled",
            "notifications/elicitation/complete",
            "notifications/message",
            "notifications/progress",
            "notifications/prompts/list_changed",
            "notifications/resources/list_changed",
            "notifications/resources/updated",
            "notifications/subscriptions/acknowledged",  # added in 2026-07-28
            "notifications/tools/list_changed",
        }
    ),
    strip_on_emit=(
        Strip(ClientCapabilities, "tasks"),  # 2025-11-25 only
        Strip(ServerCapabilities, "tasks"),  # 2025-11-25 only
        Strip(CallToolRequestParams, "task"),  # 2025-11-25 only
        Strip(CreateMessageRequestParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestFormParams, "task"),  # 2025-11-25 only
        Strip(ElicitRequestURLParams, "task"),  # 2025-11-25 only
        Strip(RootsCapability, "listChanged"),  # removed in 2026-07-28
    ),
    inject_on_emit=(
        # resultType is required on every 2026-07-28 result; absent means
        # complete, and an input-required result is its own type.
        Inject(Result, "resultType", "complete"),
        Inject(InputRequiredResult, "resultType", "input_required"),
        # Both caching fields are required on 2026-07-28 cacheable results;
        # when a handler leaves them unset the don't-cache pair is supplied.
        # OD-5 alternative: require handlers to set ttlMs/cacheScope instead.
        Inject(CacheableResult, "ttlMs", 0),
        Inject(CacheableResult, "cacheScope", "private"),
    ),
    refuse_on_emit=(
        # The 2026-07-28 schema requires at least one of inputRequests /
        # requestState (stated in prose; both fields are optional in the
        # schema, so the check cannot ride validation).
        Refuse(
            InputRequiredResult,
            _empty_input_required,
            "input-required result with neither inputRequests nor requestState",
        ),
    ),
    # Every 2026-07-28 request must carry the reserved _meta keys: the
    # protocol version, client info, and client capabilities ride each
    # request instead of an initialize handshake.
    meta_required_methods=frozenset(
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
    # The 2026-07-28 ResultType description names exactly these two values;
    # the union is open for future revisions, but a present-and-unrecognized
    # inbound value is rejected at this version.
    recognized_result_types=frozenset({"complete", "input_required"}),
)


VERSION_FACTS: Final[Mapping[str, VersionFacts]] = MappingProxyType(
    {facts.version: facts for facts in (V2024_11_05, V2025_03_26, V2025_06_18, V2025_11_25, V2026_07_28)}
)
"""All per-version fact blocks, keyed by version string, oldest to newest.

`mcp.shared.version.KNOWN_PROTOCOL_VERSIONS` is the canonical registry; the
agreement between that tuple and these blocks is asserted by
`tests/types/test_version_registry.py`.
"""
