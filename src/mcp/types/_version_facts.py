"""Per-version method tables and the two wire-surface fact blocks.

The type layer keys its wire knowledge at two different granularities:

- METHOD TABLES are per protocol version. Which wire methods exist in each
  direction is genuine per-version dispatch data, stated below as literal
  frozensets, oldest version to newest. The session layer consumes these for
  dispatch gating; the type layer only classifies.
- EMISSION AND PARSE SHAPING is per wire surface, and there are exactly two
  surfaces: `v2025_11_25`, serving every version at or below 2025-11-25, and
  `v2026_07_28`, serving the new protocol. One surface can serve the four
  older versions because their schema evolution is strictly additive
  (`tests/types/test_version_facts_oracle.py` proves this oracle by oracle).

The `v2025_11_25` surface block is empty on purpose: emission on those
versions is the plain monolith dump and parsing is the plain superset parse.
Nothing is injected (no version at or below 2025-11-25 requires a field the
dump lacks), nothing is stripped (every deployed SDK ignores or preserves
unknown object keys, so deleting a caller-set field would re-shape the
message for no benefit), and nothing is refused (whether a newer construct —
tool sampling content, url-mode elicitation, an input-required result, ... —
may be SENT to a given peer is a session-layer gate on the negotiated
version or capability, applied before the value reaches this boundary). The
`v2026_07_28` block carries the new protocol's required-field injections,
its emission refusals, and its inbound mandates.

This module is data plus the small named predicates the rows point at. The
engine that interprets the rows lives in `mcp.types._shaping`; the public
entry points live in `mcp.types.wire`.
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
    CancelTaskRequest,
    CancelTaskResult,
    CreateMessageResult,
    CreateMessageResultWithTools,
    CreateTaskResult,
    ElicitResult,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskResult,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    InputRequiredResult,
    ListRootsResult,
    ListTasksRequest,
    ListTasksResult,
    PingRequest,
    Result,
    RootsListChangedNotification,
    SetLevelRequest,
    SubscribeRequest,
    TaskStatusNotification,
    UnsubscribeRequest,
)


class UnsupportedAtVersionError(ValueError):
    """The value cannot be legally represented on this version's wire.

    Raised on 2026-07-28 serialization only, in exactly three cases: a
    request whose `params._meta` lacks a caller-supplied client identity key,
    an input-required result with neither `inputRequests` nor `requestState`
    set, and a value whose type the 2026-07-28 schema does not define (the
    removed lifecycle/logging/subscription messages and the 2025-11-25 task
    types). Serialization at 2025-11-25 and earlier never raises this: there
    the emitted body is the plain model dump. Defined here so both the
    engine and the boundary can raise it; re-exported by `mcp.types.wire` as
    part of the public surface.
    """

    def __init__(self, version: str, message: str) -> None:
        super().__init__(message)
        self.version: str = version


@dataclass(frozen=True)
class Inject:
    """This surface's wire requires the field: set `value` when the dump lacks
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

    unless: tuple[type[BaseModel], ...] = ()
    """Carve-outs from the owner's isinstance fan-out: instances of these
    classes are not injected. Used where the schema defines the field on a
    base shape but not on specific subtypes."""


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
class SurfaceFacts:
    """Everything the type layer knows about one wire surface's shaping."""

    inject_on_emit: tuple[Inject, ...]
    refuse_on_emit: tuple[Refuse, ...]
    meta_required_methods: frozenset[str]
    """Methods whose request params `_meta` must carry the reserved
    io.modelcontextprotocol keys (protocolVersion, clientInfo,
    clientCapabilities): on emission the container is materialized and
    protocolVersion injected; on parse all three keys are required."""

    recognized_result_types: frozenset[str]
    """Accepted `resultType` values on parse; empty = no mandate (any value
    parses on this surface)."""


# ----------------------------------------------------------------------------
# Named predicates for the rows that condition on a value, not just a type.
# Each one states a single wire fact checkable against the pinned public
# schemas; none contains version logic — the block a row sits in is the only
# version scope.
# ----------------------------------------------------------------------------


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
    is the `meta_required_methods` scalar of the surface block — hence the
    only predicate here without a leading underscore: it crosses a module
    boundary.
    """
    params = model.params
    meta = params.meta if params is not None else None
    return meta is None or CLIENT_INFO_META_KEY not in meta or CLIENT_CAPABILITIES_META_KEY not in meta


# ============================================================================
# Method tables, one entry per version, oldest to newest.
# Pinned schemas: schema/<version>/schema.ts @ 6d441518
# (github.com/modelcontextprotocol/modelcontextprotocol; 2026-07-28 is
# schema/draft at that commit). Verified against the generated oracles in
# tests/spec_oracles by tests/types/test_version_registry.py.
#
# The 2025-11-25 schema also defines four task request methods (tasks/cancel,
# tasks/get, tasks/list, tasks/result) in both request directions. They are
# deliberately absent from these tables: this SDK models the task payload
# types for compatibility but never dispatches the methods (tasks continue as
# an extension). notifications/tasks/status stays: it is a method fact of the
# 2025-11-25 schema, and the tables classify methods regardless of whether
# the SDK's unions carry the payload type.
#
# 2026-07-28 removes the initialize handshake (replaced by server/discover
# plus per-request `_meta`), logging/setLevel, the resources subscribe and
# unsubscribe pair (replaced by subscriptions/listen), ping, and the entire
# standalone server-to-client request channel (sampling, roots, and
# elicitation requests become payloads embedded in input-required results).
# ============================================================================

_CORE_CLIENT_REQUESTS = frozenset(
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
)
"""Client requests of the 2024-11-05 schema; unchanged through 2025-11-25."""

CLIENT_REQUEST_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "2024-11-05": _CORE_CLIENT_REQUESTS,
        "2025-03-26": _CORE_CLIENT_REQUESTS,
        "2025-06-18": _CORE_CLIENT_REQUESTS,
        "2025-11-25": _CORE_CLIENT_REQUESTS,
        "2026-07-28": frozenset(
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
    }
)
"""Client-to-server request methods defined at each protocol version."""

_CORE_CLIENT_NOTIFICATIONS = frozenset(
    {
        "notifications/cancelled",
        "notifications/initialized",
        "notifications/progress",
        "notifications/roots/list_changed",
    }
)
"""Client notifications of the 2024-11-05 schema; unchanged through 2025-06-18."""

CLIENT_NOTIFICATION_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "2024-11-05": _CORE_CLIENT_NOTIFICATIONS,
        "2025-03-26": _CORE_CLIENT_NOTIFICATIONS,
        "2025-06-18": _CORE_CLIENT_NOTIFICATIONS,
        "2025-11-25": _CORE_CLIENT_NOTIFICATIONS | {"notifications/tasks/status"},  # added in 2025-11-25
        "2026-07-28": frozenset(
            {
                "notifications/cancelled",
                "notifications/progress",
            }
        ),
    }
)
"""Client-to-server notification methods defined at each protocol version."""

_CORE_SERVER_REQUESTS = frozenset(
    {
        "ping",
        "roots/list",
        "sampling/createMessage",
    }
)
"""Server requests of the 2024-11-05 schema; elicitation/create joins in 2025-06-18."""

SERVER_REQUEST_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "2024-11-05": _CORE_SERVER_REQUESTS,
        "2025-03-26": _CORE_SERVER_REQUESTS,
        "2025-06-18": _CORE_SERVER_REQUESTS | {"elicitation/create"},  # added in 2025-06-18
        "2025-11-25": _CORE_SERVER_REQUESTS | {"elicitation/create"},
        "2026-07-28": frozenset(),  # 2026-07-28 removed server-to-client requests
    }
)
"""Server-to-client request methods defined at each protocol version."""

_CORE_SERVER_NOTIFICATIONS = frozenset(
    {
        "notifications/cancelled",
        "notifications/message",
        "notifications/progress",
        "notifications/prompts/list_changed",
        "notifications/resources/list_changed",
        "notifications/resources/updated",
        "notifications/tools/list_changed",
    }
)
"""Server notifications of the 2024-11-05 schema; unchanged through 2025-06-18."""

SERVER_NOTIFICATION_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "2024-11-05": _CORE_SERVER_NOTIFICATIONS,
        "2025-03-26": _CORE_SERVER_NOTIFICATIONS,
        "2025-06-18": _CORE_SERVER_NOTIFICATIONS,
        # elicitation/complete and tasks/status notifications added in 2025-11-25.
        "2025-11-25": _CORE_SERVER_NOTIFICATIONS | {"notifications/elicitation/complete", "notifications/tasks/status"},
        "2026-07-28": _CORE_SERVER_NOTIFICATIONS
        | {"notifications/elicitation/complete", "notifications/subscriptions/acknowledged"},
    }
)
"""Server-to-client notification methods defined at each protocol version."""


# ============================================================================
# Surface v2025_11_25 — serves every version at or below 2025-11-25.
# Pinned schemas: schema/{2024-11-05,2025-03-26,2025-06-18,2025-11-25}/
# schema.ts @ 6d441518.
# ============================================================================
V2025_11_25 = SurfaceFacts(
    # Every cell empty, on purpose: emission on these versions is the plain
    # monolith dump and parsing is the plain superset parse, with no
    # transformations in either direction. No schema at or below 2025-11-25
    # requires a field the dump lacks, so there is nothing to inject; fields
    # a version's schema does not define are emitted anyway, because every
    # deployed SDK ignores or preserves unknown object keys, while silently
    # deleting a caller-set value would re-shape the message the caller
    # built; and constructs a peer may genuinely not understand (newer union
    # members and enum values: tool sampling content, url-mode elicitation,
    # an input-required result body, ...) are for the session layer to gate
    # by negotiated version or capability before they reach this boundary —
    # peers reject unknown union TAGS, not unknown KEYS, and only the
    # session knows what was negotiated. The one narrow deployed-peer hazard
    # of emitting an unknown key (strict empty-result peers) is documented
    # on the monolith's `Result.result_type` field.
    inject_on_emit=(),
    refuse_on_emit=(),
    meta_required_methods=frozenset(),
    recognized_result_types=frozenset(),
)


# ============================================================================
# Surface v2026_07_28 — the new protocol.
# Pinned schema: schema/draft/schema.ts @ 6d441518, protocol revision
# 2026-07-28. Verified against the generated oracle
# tests/spec_oracles/v2026_07_28.py by tests/types/test_version_facts_oracle.py.
# ============================================================================
V2026_07_28 = SurfaceFacts(
    inject_on_emit=(
        # resultType is required on every top-level 2026-07-28 result; absent
        # means complete, and an input-required result is its own type. The
        # schema defines the field on the Result base and on every server
        # result, but NOT on the three input-response payloads (the sampling,
        # elicitation, and roots results lost their top-level response frame
        # when the revision removed server-to-client requests), so those are
        # carved out of the base row's fan-out. The two sampling result
        # classes share one schema definition (the SDK splits the single-block
        # shape from the array/tool-content shape), so both are carved out.
        Inject(
            Result,
            "resultType",
            "complete",
            unless=(CreateMessageResult, CreateMessageResultWithTools, ElicitResult, ListRootsResult),
        ),
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
        # The 2026-07-28 schema does not define these types — the revision
        # removed the initialize handshake, ping, logging/setLevel, the
        # per-URI resources subscribe/unsubscribe pair, the standalone roots
        # list_changed notification, and the experimental 2025-11-25 task
        # system (tasks continue as an extension) — so values of these types
        # have no legal 2026-07-28 wire form. On every other version the same
        # values dump plainly. (The removed server-to-client REQUESTS —
        # sampling, roots, elicitation — are not here: the schema keeps their
        # payload types as embedded input-request/input-response values.)
        Refuse(InitializeRequest, None, "the initialize request"),
        Refuse(InitializeResult, None, "the initialize result"),
        Refuse(InitializedNotification, None, "the initialized notification"),
        Refuse(PingRequest, None, "the ping request"),
        Refuse(SetLevelRequest, None, "the logging/setLevel request"),
        Refuse(SubscribeRequest, None, "the resources/subscribe request"),
        Refuse(UnsubscribeRequest, None, "the resources/unsubscribe request"),
        Refuse(RootsListChangedNotification, None, "the roots list_changed notification"),
        Refuse(CreateTaskResult, None, "the task-augmented-request result"),
        Refuse(GetTaskRequest, None, "the tasks/get request"),
        Refuse(GetTaskResult, None, "the tasks/get result"),
        Refuse(ListTasksRequest, None, "the tasks/list request"),
        Refuse(ListTasksResult, None, "the tasks/list result"),
        Refuse(CancelTaskRequest, None, "the tasks/cancel request"),
        Refuse(CancelTaskResult, None, "the tasks/cancel result"),
        Refuse(GetTaskPayloadRequest, None, "the tasks/result request"),
        Refuse(GetTaskPayloadResult, None, "the tasks/result result"),
        Refuse(TaskStatusNotification, None, "the task status notification"),
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


SURFACE_FACTS: Final[Mapping[str, SurfaceFacts]] = MappingProxyType(
    {
        "2024-11-05": V2025_11_25,
        "2025-03-26": V2025_11_25,
        "2025-06-18": V2025_11_25,
        "2025-11-25": V2025_11_25,
        "2026-07-28": V2026_07_28,
    }
)
"""Version -> surface block, the map every boundary call goes through.

`mcp.shared.version.KNOWN_PROTOCOL_VERSIONS` is the canonical registry; the
agreement between that tuple and these keys is asserted by
`tests/types/test_version_registry.py`.
"""
