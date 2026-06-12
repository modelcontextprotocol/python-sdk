"""Version-aware wire boundary for MCP types.

Serialize a monolith model for, or parse wire data under, a specific
negotiated protocol version. A "monolith" model is one of the version-superset
models in ``mcp.types._types``: one class per protocol construct, carrying
every supported version's fields, in contrast to the per-version wire-shape
packages (``mcp.types.v*``). The unique key for every behavior in this module
is (monolith type, negotiated version). Versions are opaque strings ordered by
``KNOWN_PROTOCOL_VERSIONS``; nothing here negotiates, dispatches, or holds
session state.

Emission works by re-validation: ``serialize_for`` dumps the monolith model,
applies a handful of explicit shaping rules (each cited inline), validates the
result through the negotiated version's wire-shape models (``mcp.types.v*`` —
imported lazily, so this module stays cheap until first use), and re-dumps.
The re-dump decides only which keys survive; emitted values always come from
the original dump. A version's required fields, union memberships, and field
existence are therefore facts readable in that version's model package rather
than rules written here. Parsing is one lenient superset parse at every
version plus the few documented 2026-07-28 inbound mandates.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from functools import cache
from types import ModuleType
from typing import Any, Final, TypeVar, cast, get_args, overload

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from mcp.shared.version import KNOWN_PROTOCOL_VERSIONS, is_version_at_least
from mcp.types._spec_names import SDK_TO_SCHEMA_RENAMES
from mcp.types._types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    AudioContent,
    CacheableResult,
    ElicitResult,
    EmbeddedResource,
    EmptyResult,
    ImageContent,
    InputRequiredResult,
    Notification,
    Request,
    RequestParams,
    ResourceLink,
    Result,
    ResultType,
    TextContent,
    ToolResultContent,
    ToolUseContent,
)
from mcp.types._versions import (
    CLIENT_NOTIFICATION_METHODS,
    CLIENT_REQUEST_METHODS,
    SERVER_NOTIFICATION_METHODS,
    SERVER_REQUEST_METHODS,
)
from mcp.types.jsonrpc import JSONRPCError, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse

__all__ = [
    "CLIENT_NOTIFICATION_METHODS",
    "CLIENT_REQUEST_METHODS",
    "KNOWN_PROTOCOL_VERSIONS",
    "SERVER_NOTIFICATION_METHODS",
    "SERVER_REQUEST_METHODS",
    "UnknownProtocolVersionError",
    "UnsupportedAtVersionError",
    "parse_as",
    "serialize_for",
]

# KNOWN_PROTOCOL_VERSIONS (the ordered version registry) lives in
# mcp.shared.version; the four per-version method tables are plain data in
# mcp.types._versions. Both are re-exported here as the boundary's public
# surface. The tables record which methods exist at each version; acting on
# that (rejecting a version-invalid request, dropping or logging a
# version-invalid notification) is session-layer behavior, as are the other
# capability-keyed halves of version shaping: the sampling tools capability
# gate for tool content on 2025-11-25 sessions, the elicitation url capability
# gate, and the per-request logLevel send condition.

_T = TypeVar("_T", bound=BaseModel)


class UnknownProtocolVersionError(ValueError):
    """``version`` is not a known protocol version (raised on emission only).

    Inbound parsing never raises this: an unknown version is most plausibly
    newer than this SDK, and lenient parsing cannot misrepresent data. On
    emission the type layer must never guess a wire shape, so
    ``serialize_for`` refuses instead.
    """

    def __init__(self, version: str) -> None:
        super().__init__(f"unknown protocol version {version!r}; known versions: {', '.join(KNOWN_PROTOCOL_VERSIONS)}")
        self.version: str = version
        self.known: tuple[str, ...] = KNOWN_PROTOCOL_VERSIONS


class UnsupportedAtVersionError(ValueError):
    """The value cannot be legally represented on this version's wire.

    Raised by ``serialize_for`` instead of silently changing meaning: for
    example an ``InputRequiredResult`` on a 2025-11-25-or-earlier session,
    tool-block or multi-block sampling content on 2025-06-18 or earlier, a
    ``CancelledNotification`` without ``request_id`` on 2025-06-18 or earlier,
    or a 2026-07-28 client request whose ``params._meta`` lacks the
    caller-supplied ``clientInfo``/``clientCapabilities`` entries.
    """

    def __init__(self, message: str, *, version: str) -> None:
        super().__init__(message)
        self.version: str = version


_VERSION_MODULES: Final[Mapping[str, str]] = {
    "2024-11-05": "mcp.types.v2024_11_05",
    "2025-03-26": "mcp.types.v2025_03_26",
    "2025-06-18": "mcp.types.v2025_06_18",
    "2025-11-25": "mcp.types.v2025_11_25",
    "2026-07-28": "mcp.types.v2026_07_28",
}
"""Module path of each known version's wire-shape model package."""

# serialize_for-only name aliases for SDK classes whose wire shape the schemas
# publish under a different export name and that the spec-name divergence map
# cannot carry (the map requires schema counterparts; these are SDK-only
# names). The SDK splits the wide-content sampling result into its own class,
# while the 2025-11-25 and 2026-07-28 schemas type the class they name
# CreateMessageResult wide.
_WIRE_NAME_ALIASES: Final[Mapping[str, str]] = {"CreateMessageResultWithTools": "CreateMessageResult"}

_ENVELOPE_MODELS: Final = (JSONRPCRequest, JSONRPCNotification, JSONRPCResponse, JSONRPCError)
_BODY_MODELS: Final = (Request, Notification, Result)

# From 2025-11-25 on, the schemas define each request and notification as a
# complete JSON-RPC frame, so the generated wire-shape classes declare the
# envelope fields (requests: jsonrpc + id; notifications: jsonrpc) as
# required. serialize_for emits message BODIES; validation supplies these
# constants and the output never carries them (dropped before alignment).
_ENVELOPE_FIELD_STUBS: Final[Mapping[str, Any]] = {"jsonrpc": "2.0", "id": 0}

_SANCTIONED_STRIPS: Final[frozenset[str]] = frozenset(
    {
        # resultType is new in 2026-07-28; on earlier versions even a
        # caller-set value is dropped — deployed peers hard-reject an empty
        # result that carries any extra key (deployed-peer-mandated).
        "resultType",
        # The caching directives are new in 2026-07-28.
        "ttlMs",
        "cacheScope",
        # The capabilities extensions field is new in 2026-07-28 and must not
        # leak by default on earlier versions.
        "extensions",
        # Task-augmented params and the capabilities tasks subtrees exist only
        # in the 2025-11-25 schema.
        "task",
        "tasks",
    }
)
"""Keys whose loss during re-validation is a sanctioned strip.

Any other key the target version's model dropped is RESTORED by the alignment
walk: newer optional fields on known types (``icons``, ``title``, ...) are
wire-safe against every deployed peer and pass through at every version, and
values are never substituted — the re-validated output decides keys only.
"""

_EMBEDDED_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset({"inputRequests", "inputResponses"})
"""Wire keys of maps whose values are embedded request/response payloads.

The boundary deliberately never reshapes embedded payloads — no injection and
no strip; below these keys every key the re-dump lost is restored verbatim.
Embedded-payload hygiene is the caller's responsibility.
"""

# The 2026-07-28 schema requires the reserved _meta entries on every client
# request, so the injection/validation rule is keyed on that revision's client
# request methods.
_REQUIRED_META_METHODS: Final[frozenset[str]] = CLIENT_REQUEST_METHODS["2026-07-28"]
_REQUIRED_META_KEYS: Final[tuple[str, ...]] = (
    PROTOCOL_VERSION_META_KEY,
    CLIENT_INFO_META_KEY,
    CLIENT_CAPABILITIES_META_KEY,
)

_RECOGNIZED_RESULT_TYPES: Final[frozenset[str]] = frozenset(
    literal for arm in get_args(ResultType) for literal in get_args(arm)
)
"""The ``resultType`` values the spec names, read from the monolith
``ResultType`` alias so the recognized set has a single source."""

_CONTENT_BLOCK_TAGS: Final[Mapping[str, Any]] = {
    block.__name__: block.model_fields["type"].default
    for block in (
        TextContent,
        ImageContent,
        AudioContent,
        ResourceLink,
        EmbeddedResource,
        ToolUseContent,
        ToolResultContent,
    )
}
"""Every monolith content-block class and its wire ``type`` tag."""


def serialize_for(model: BaseModel, version: str) -> dict[str, Any]:
    """Dump ``model`` as its wire JSON for a session negotiated at ``version``.

    ``model`` is a top-level message body (a concrete request, notification,
    or result model) or a ``mcp.types.jsonrpc`` envelope model; any other
    monolith model (a bare fragment: content blocks, ``SamplingMessage``,
    capabilities objects, params classes, ...) raises ``TypeError`` —
    fragments are shaped only in situ, inside the body that carries them.

    Returns the message body (requests/notifications/results) or the full
    frame when given an envelope model. Shaping is version-keyed: injections
    fire only on the versions that require a construct, and strips fire on
    the versions that lack it — whether the version predates the construct
    (``resultType`` before 2026-07-28) or postdates its removal (``task``
    metadata and the roots capability's ``listChanged`` flag at 2026-07-28).
    The mechanism decides KEYS only: emitted leaf values always come from the
    monolith dump, never from a version package's re-validated output. For
    values that use only constructs the target version defines, dumps for
    2025-11-25 and earlier are byte-identical to a plain
    ``model_dump(by_alias=True, mode="json", exclude_none=True)`` of the same
    value; a caller-set field the target version lacks (``resultType``,
    ``ttlMs``, ``cacheScope``, capability ``extensions``, ...) is stripped
    there, so the dump then differs from the plain one by exactly that strip.
    Null-valued elicitation content entries — constructible for v1.x
    compatibility, typed by no schema version — are caller data and pass
    through verbatim at every version that models elicitation.

    On 2026-07-28 sessions, client requests must already carry the
    caller-supplied ``clientInfo`` and ``clientCapabilities`` entries in
    ``params._meta``; sourcing session identity is the session layer's job,
    and the boundary injects only ``protocolVersion``.

    A re-validation failure is reported as ``UnsupportedAtVersionError`` and
    cannot distinguish a value the target revision truly cannot express from a
    defect in that revision's model package; when a raise surprises you, read
    the chained validation error and check the ``mcp.types.v*`` package first.

    Raises:
        UnknownProtocolVersionError: ``version`` is not a known protocol
            version.
        UnsupportedAtVersionError: ``model`` has no legal wire form at
            ``version`` — its type or content does not exist in that
            revision's schema, or a 2026-07-28 client request is missing the
            caller-supplied identity entries above.
    """
    if not _is_serializable_payload(model):
        raise TypeError("serialize_for expects a message body or an envelope model")
    if version not in KNOWN_PROTOCOL_VERSIONS:
        raise UnknownProtocolVersionError(version)
    dump = model.model_dump(by_alias=True, mode="json", exclude_none=True)
    if isinstance(model, _ENVELOPE_MODELS):
        # Envelope frames are version-independent, and the untyped
        # params/result interior of a generic envelope passes through opaque:
        # payload shaping happens when the typed payload model itself is
        # serialized, never by inspecting an untyped dict.
        return dump
    shaped = _shape_for_version(model, dump, version)
    wire_cls = _wire_class(type(model), version)
    stubs = {key: value for key, value in _ENVELOPE_FIELD_STUBS.items() if key in wire_cls.model_fields}
    try:
        revalidated = wire_cls.model_validate({**stubs, **_revalidation_view(model, shaped)})
    except ValidationError as err:
        raise UnsupportedAtVersionError(
            f"{type(model).__name__} has no legal wire form at protocol version {version}: {_summarize(err)}",
            version=version,
        ) from err
    redump = revalidated.model_dump(by_alias=True, mode="json", exclude_unset=True)
    for key in stubs:
        del redump[key]
    return _merge_and_align(shaped, redump)


def _is_serializable_payload(model: BaseModel) -> bool:
    """True when ``model`` is in ``serialize_for``'s payload domain."""
    return isinstance(model, _BODY_MODELS) or isinstance(model, _ENVELOPE_MODELS)


def _shape_for_version(model: BaseModel, dump: dict[str, Any], version: str) -> dict[str, Any]:
    """Apply the hand-written emission rules to a monolith body dump.

    Five rules, all keyed to 2026-07-28; everything else about a version's
    wire shape (required fields, union membership, dropped fields) is read
    from that version's model package by re-validation. The rules touch the
    top-level body only — embedded request/response payloads (the
    ``inputRequests``/``inputResponses`` map values) are never recursed into.
    """
    # OD-11 alternative: narrow outbound values to the target revision's declared shapes on older versions.
    if not is_version_at_least(version, "2026-07-28"):
        return dump
    if isinstance(model, Result):
        # resultType is required on 2026-07-28 results; absent means
        # "complete", and an input-required result must say so. A caller-set
        # value is never overwritten.
        dump.setdefault("resultType", "input_required" if isinstance(model, InputRequiredResult) else "complete")
    if isinstance(model, CacheableResult):
        # ttlMs/cacheScope are required on these results from 2026-07-28;
        # when the handler leaves them unset the boundary fills the
        # don't-cache pair: immediately stale, single-user scope.
        # OD-5 alternative: inject nothing and require handlers to set both fields.
        dump.setdefault("ttlMs", 0)
        dump.setdefault("cacheScope", "private")
    if isinstance(model, Request) and dump.get("method") in _REQUIRED_META_METHODS:
        # 2026-07-28 client requests carry the reserved _meta entries.
        # protocolVersion is the one entry derivable here and is merged
        # without overwriting a caller-set value; clientInfo and
        # clientCapabilities are session identity, never synthesized — when
        # absent, re-validation below refuses loudly.
        params: dict[str, Any] = dump.setdefault("params", {})
        meta: dict[str, Any] = params.setdefault("_meta", {})
        meta.setdefault(PROTOCOL_VERSION_META_KEY, version)
    if isinstance(model, Request):
        # 2026-07-28 removed the roots capability's listChanged flag; the
        # capability itself survives and emits without it. The schema types
        # the capability as a plain object, so re-validation alone cannot
        # drop the flag.
        meta_value = _dict_value(dump, "params", "_meta")
        capabilities = _dict_value(meta_value, CLIENT_CAPABILITIES_META_KEY) if meta_value is not None else None
        roots = _dict_value(capabilities, "roots") if capabilities is not None else None
        if roots is not None:
            roots.pop("listChanged", None)
    if isinstance(model, InputRequiredResult) and model.input_requests is None and model.request_state is None:
        # The 2026-07-28 schema requires at least one of
        # inputRequests/requestState on the wire; the requirement is spec
        # prose (both fields are optional in the schema's type), so
        # re-validation cannot enforce it.
        raise UnsupportedAtVersionError(
            "InputRequiredResult with neither input_requests nor request_state set "
            f"has no legal wire form at protocol version {version}",
            version=version,
        )
    return dump


def _revalidation_view(model: BaseModel, shaped: dict[str, Any]) -> dict[str, Any]:
    """The shaped dump as re-validation sees it; the output base is untouched.

    Null-valued elicitation content entries are withheld from the dict handed
    to the version package: no schema version types a null form answer (the
    monolith admits ``None`` values for v1.x constructor compatibility), and
    emitted values are caller data the boundary passes through verbatim
    rather than narrowing or refusing — python v1.x itself constructs,
    accepts, and emits the same body. The withheld entries are keys the
    re-dump lost, so the alignment walk restores them from the shaped dump.
    Every other value reaches the version package unchanged: a value the
    target version truly cannot express still refuses loudly.
    """
    if not isinstance(model, ElicitResult):
        return shaped
    content = shaped.get("content")
    if not isinstance(content, dict):
        return shaped
    entries = cast("dict[str, Any]", content)
    if all(value is not None for value in entries.values()):
        return shaped
    view = dict(shaped)
    view["content"] = {key: value for key, value in entries.items() if value is not None}
    return view


def _dict_value(mapping: Mapping[str, Any], *keys: str) -> dict[str, Any] | None:
    """Walk ``keys`` through nested dicts; ``None`` as soon as one is not a dict."""
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = cast("dict[str, Any]", value).get(key)
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _version_module(version: str) -> ModuleType:
    """Import (on first use) and return the wire-shape models for ``version``.

    Loaded lazily so importing ``mcp.types`` (or this module) never pays for
    the per-version model packages; ``sys.modules`` caches after the first
    boundary call for a version.
    """
    return importlib.import_module(_VERSION_MODULES[version])


def _wire_class(cls: type[BaseModel], version: str) -> type[BaseModel]:
    """Return the ``version`` package's model class for the monolith ``cls``.

    Lookup is by name: the monolith name itself, then the schema-side name
    where the SDK deliberately diverges. A miss means the type has no wire
    form at that version (its schema does not define it).
    """
    module = _version_module(version)
    for name in (cls.__name__, SDK_TO_SCHEMA_RENAMES.get(cls.__name__), _WIRE_NAME_ALIASES.get(cls.__name__)):
        if name is not None:
            found = getattr(module, name, None)
            if found is not None:
                return found
    raise UnsupportedAtVersionError(f"{cls.__name__} has no wire form at protocol version {version}", version=version)


def _summarize(err: ValidationError) -> str:
    """One line for the first validation error (the full chain is preserved)."""
    first = err.errors()[0]
    where = ".".join(str(segment) for segment in first["loc"]) or "<body>"
    remainder = f" (+{err.error_count() - 1} more)" if err.error_count() > 1 else ""
    return f"{where}: {first['msg']}{remainder}"


def _merge_and_align(shaped: dict[str, Any], redump: dict[str, Any], strips_apply: bool = True) -> dict[str, Any]:
    """Merge the re-validated dump back onto the shaped monolith dump.

    The re-dump decides KEYS only — values are never substituted: every
    emitted leaf value comes from the shaped monolith dump, never from the
    re-validated model, whose validation may have coerced a value (an int
    bound re-rendered through a float field, or vice versa). The output
    follows the shaped dump's key order: pydantic re-dumps in model field
    order, while dumps for 2025-11-25 and earlier must stay byte-identical to
    the monolith dump. A key the re-dump lost is restored unless its loss is
    a sanctioned strip (and never inside embedded payload maps, where
    everything is restored); a key the re-dump invented is always a defect in
    the version package.
    """
    merged: dict[str, Any] = {}
    for key, shaped_value in shaped.items():
        if key not in redump:
            if not (strips_apply and key in _SANCTIONED_STRIPS):
                merged[key] = shaped_value
            continue
        merged[key] = _align_value(shaped_value, redump[key], strips_apply and key not in _EMBEDDED_PAYLOAD_KEYS)
    invented = redump.keys() - shaped.keys()
    if invented:
        raise RuntimeError(f"re-validation for the target version invented output keys: {sorted(invented)}")
    return merged


def _align_value(shaped_value: Any, redump_value: Any, strips_apply: bool) -> Any:
    """Walk shaped and re-dumped values in parallel; the shaped side wins at leaves."""
    if isinstance(redump_value, dict) and isinstance(shaped_value, dict):
        return _merge_and_align(
            cast("dict[str, Any]", shaped_value), cast("dict[str, Any]", redump_value), strips_apply
        )
    if isinstance(redump_value, list) and isinstance(shaped_value, list):
        shaped_items = cast("list[Any]", shaped_value)
        redump_items = cast("list[Any]", redump_value)
        return [
            _align_value(shaped_item, redump_item, strips_apply)
            for shaped_item, redump_item in zip(shaped_items, redump_items, strict=True)
        ]
    return shaped_value


@overload
def parse_as(type_: type[_T], data: Mapping[str, Any], version: str) -> _T: ...
@overload
def parse_as(type_: Any, data: Mapping[str, Any], version: str) -> Any: ...
def parse_as(type_: Any, data: Mapping[str, Any], version: str) -> Any:
    """Validate inbound wire ``data`` as ``type_`` under ``version`` semantics.

    ``type_`` is a monolith model class or a public union alias
    (``ClientRequest``, ``ServerResult``, ``ContentBlock``,
    ``JSONRPCMessage``, ...). Parsing is one lenient superset parse at every
    version — unknown fields are never rejected — plus the 2026-07-28
    inbound mandates: a result carrying an unrecognized ``resultType`` value
    is rejected, a client request must carry all three reserved ``_meta``
    entries, and embedded input-request entries must each carry ``method``.
    Result-bearing unions resolve their member structurally: every arm
    recognizing more of the payload's top-level keys than the base ``Result``
    is a candidate, candidates are validated best match first, and the first
    success wins — so the open-shaped ``EmptyResult`` arm cannot mask a
    better-matching member's validation failures, and a body its best-looking
    arm rejects still parses when a sibling arm accepts it. When every
    candidate fails, the best-ranked arm's errors surface; unknown-shaped
    result bodies still parse (as the ``EmptyResult`` arm). Unknown
    ``version`` strings parse leniently with NO version-keyed mandates
    applied, and never raise for the version string itself.

    Raises:
        pydantic.ValidationError: ``data`` is not valid for ``type_`` at
            ``version``.
    """
    apply_mandates = is_version_at_least(version, "2026-07-28")
    result_arms = _result_union_arms(type_)
    if result_arms is None:
        parsed = _validate_refined(type_, data)
    elif apply_mandates and InputRequiredResult in result_arms and data.get("resultType") == "input_required":
        # 2026-07-28 response bodies discriminate by resultType: an
        # input-required body must resolve to InputRequiredResult even when it
        # also carries fields of another member. Union targets only — a
        # concrete `type_` always parses as the requested class.
        parsed = _validate_refined(InputRequiredResult, data)
    else:
        parsed = _validate_first(_select_result_arms(result_arms, data), data)
    if apply_mandates:
        _reject_unrecognized_result_type(type_, data)
        _reject_input_request_entries_without_method(parsed)
        _reject_missing_required_meta(parsed)
    return parsed


@cache
def _adapter(type_: Any) -> TypeAdapter[Any]:
    """One ``TypeAdapter`` per parse target, cached on the type object."""
    return TypeAdapter[Any](type_)


@cache
def _result_union_arms(type_: Any) -> tuple[type[Result], ...] | None:
    """The member tuple when ``type_`` is a union of ``Result`` subclasses
    (``ServerResult``, ``ClientResult``); ``None`` for anything else."""
    arms = get_args(type_)
    if arms and all(isinstance(arm, type) and issubclass(arm, Result) for arm in arms):
        return cast("tuple[type[Result], ...]", arms)
    return None


@cache
def _wire_field_names(cls: type[BaseModel]) -> frozenset[str]:
    """A model's wire-facing key set: each field's alias when it has one."""
    return frozenset(field.alias or name for name, field in cls.model_fields.items())


def _select_result_arms(arms: tuple[type[Result], ...], data: Mapping[str, Any]) -> tuple[type[Result], ...]:
    """Rank the result-union members that could own the payload, best first.

    A plain smart-union parse cannot do this job: ``EmptyResult`` declares no
    required fields, so it validates EVERY JSON object and would swallow the
    validation failures of a better-matching member — a discover result
    missing its required ``supportedVersions`` and a tool result whose content
    carries an unknown ``type`` must reject, not quietly fall back to
    ``EmptyResult``. Every arm recognizing strictly more of the payload's
    top-level keys than the base ``Result`` fields is a candidate, ranked by
    recognized-key count with ties kept in union declaration order. Key
    counting cannot tell apart sibling arms with identical top-level key sets
    (the single-content and array-content sampling results differ only in the
    SHAPE of ``content``), so the caller validates candidates in rank order
    and the first success wins. When no arm beats base ``Result`` the body
    parses as the ``EmptyResult`` arm. The selection is version-free and
    ignores unknown fields, so inbound leniency is untouched.
    """
    payload_keys = frozenset(data)
    base = len(payload_keys & _wire_field_names(Result))
    scores = {arm: len(payload_keys & _wire_field_names(arm)) for arm in arms}
    candidates = sorted((arm for arm in arms if scores[arm] > base), key=lambda arm: -scores[arm])
    return tuple(candidates) if candidates else (EmptyResult,)


def _validate_first(targets: tuple[type[Result], ...], data: Mapping[str, Any]) -> Any:
    """Validate ``data`` against each target in order; the first success wins.

    When every target rejects, the surfaced error is the FIRST target's: the
    best-ranked candidate is the arm the payload most resembles, so its
    errors (refined exactly like a single-target parse) describe the failure.
    """
    first, *rest = targets
    try:
        return _validate_refined(first, data)
    except ValidationError:
        for target in rest:
            try:
                return _validate_refined(target, data)
            except ValidationError:
                continue
        raise


def _validate_refined(type_: Any, data: Mapping[str, Any]) -> Any:
    """Superset-parse ``data`` as ``type_``, refining unknown content tags."""
    try:
        return _adapter(type_).validate_python(data)
    except ValidationError as err:
        refined = _refine_unknown_content_type(err, data)
        if refined is None:
            raise
        raise refined from err


def _refine_unknown_content_type(err: ValidationError, data: Mapping[str, Any]) -> ValidationError | None:
    """Convert per-arm failures on an unknown content ``type`` tag into a
    single unknown-tag error at the failing location.

    The monolith content unions are plain unions (their pre-2026 shape), so an
    unknown ``type`` value fails every arm with per-arm structural errors
    rather than one tag error — but an unknown content type is an unknown
    union member to every deployed SDK, including when it fails nested inside
    a parsed result's ``content`` list. Only a dict whose ``type`` value is a
    string outside the failing arms' tag set is converted: a recognized tag
    with bad fields, and a tag-less entry (e.g. an input-request entry with no
    ``method``), keep their structural errors.

    A plain-union error location is ``(..., "<ArmClassName>", "<field>")``
    (verified against pydantic 2.12); the arm-name segment is how
    content-union failures are recognized here.
    """
    failing_locations: dict[tuple[str | int, ...], set[str]] = {}
    for line in err.errors():
        location = line["loc"]
        for index, segment in enumerate(location):
            if isinstance(segment, str) and segment in _CONTENT_BLOCK_TAGS:
                failing_locations.setdefault(location[:index], set()).add(segment)
                break
    line_errors: list[InitErrorDetails] = []
    for location, arm_names in failing_locations.items():
        fragment: Any = data
        for segment in location:
            fragment = fragment[segment]
        if not isinstance(fragment, dict):
            continue
        tag = cast("dict[str, Any]", fragment).get("type")
        expected_tags = sorted(str(_CONTENT_BLOCK_TAGS[name]) for name in arm_names)
        if isinstance(tag, str) and tag not in expected_tags:
            line_errors.append(
                InitErrorDetails(
                    type=PydanticCustomError(
                        "union_tag_invalid",
                        "Input tag '{tag}' found using {discriminator} does not match any of the "
                        "expected tags: {expected_tags}",
                        {
                            "discriminator": "'type'",
                            "tag": tag,
                            "expected_tags": ", ".join(repr(expected) for expected in expected_tags),
                        },
                    ),
                    loc=location,
                    input=fragment,
                )
            )
    if not line_errors:
        return None
    return ValidationError.from_exception_data(err.title, line_errors)


def _reject_unrecognized_result_type(type_: Any, data: Mapping[str, Any]) -> None:
    """2026-07-28 inbound mandate: an unrecognized ``resultType`` rejects.

    Applies when the parse target is a ``Result`` class or a result-bearing
    union — a stray ``resultType`` key on a request or any other type is an
    ordinary unknown field and stays accepted. An absent field is accepted
    (the spec defines absence as "complete") and a recognized value is
    retained; only a present-and-unrecognized string value rejects, with the
    pinned error type ``result_type_invalid``.
    """
    if not _is_result_parse_target(type_):
        return
    value = data.get("resultType")
    if isinstance(value, str) and value not in _RECOGNIZED_RESULT_TYPES:
        raise ValidationError.from_exception_data(
            getattr(type_, "__name__", "Result"),
            [
                InitErrorDetails(
                    type=PydanticCustomError(
                        "result_type_invalid",
                        "unrecognized resultType {result_type}; this protocol version defines "
                        "'complete' and 'input_required'",
                        {"result_type": value},
                    ),
                    loc=("resultType",),
                    input=value,
                )
            ],
        )


def _reject_input_request_entries_without_method(parsed: Any) -> None:
    """2026-07-28 inbound mandate: embedded input-request entries carry
    ``method``.

    The values of an input-required result's ``inputRequests`` map are full
    request payloads, and the schema requires ``method`` on every request. The
    monolith request models default their method literal (so handler code can
    construct them without boilerplate), which would let a method-less entry
    quietly validate as the one member whose remaining fields are all
    optional; the mandate instead checks that every entry actually supplied
    the field. A missing ``method`` is a structural failure (plain ``missing``
    error), not an unknown union member.
    """
    if not isinstance(parsed, InputRequiredResult) or parsed.input_requests is None:
        return
    missing = [key for key, entry in parsed.input_requests.items() if "method" not in entry.model_fields_set]
    if missing:
        raise ValidationError.from_exception_data(
            type(parsed).__name__,
            [InitErrorDetails(type="missing", loc=("inputRequests", key, "method"), input=None) for key in missing],
        )


def _is_result_parse_target(type_: Any) -> bool:
    """True when ``type_`` is a ``Result`` class or a result-bearing union."""
    if isinstance(type_, type):
        return issubclass(cast("type[object]", type_), Result)
    return _result_union_arms(type_) is not None


def _reject_missing_required_meta(parsed: Any) -> None:
    """2026-07-28 inbound mandate: client requests carry the reserved
    ``_meta`` triple.

    Every 2026-07-28 client request requires the
    ``io.modelcontextprotocol/{protocolVersion,clientInfo,clientCapabilities}``
    entries in ``params._meta``, each independently; a missing ``params``, a
    missing ``_meta``, or any missing entry rejects with the pinned error type
    ``missing_required_meta`` (one error per missing entry).
    """
    if not isinstance(parsed, Request):
        return
    request = cast("Request[Any, Any]", parsed)
    if request.method not in _REQUIRED_META_METHODS:
        return
    params = request.params
    meta: Mapping[str, Any] = params.meta if isinstance(params, RequestParams) and params.meta is not None else {}
    missing = [key for key in _REQUIRED_META_KEYS if key not in meta]
    if missing:
        raise ValidationError.from_exception_data(
            type(request).__name__,
            [
                InitErrorDetails(
                    type=PydanticCustomError(
                        "missing_required_meta",
                        "required reserved _meta entry {meta_key} is missing",
                        {"meta_key": key},
                    ),
                    loc=("params", "_meta", key),
                    input=dict(meta),
                )
                for key in missing
            ],
        )
