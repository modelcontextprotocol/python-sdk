"""The one interpreter for the wire-surface fact blocks.

`mcp.types.wire` calls exactly two entry points: `serialize` and `parse`.
The engine consumes the row vocabulary of `mcp.types._version_facts` and
contains no per-version and no per-family shaping knowledge of its own. Its
only fixed anchors are:

- the `mcp.types.jsonrpc` envelope models — dumped verbatim, because envelope
  shape is version-invariant;
- the `Result` base class, the `InputRequiredResult` class, and the literal
  ``"resultType"`` wire key — result-bearing unions resolve their member
  structurally, with a `resultType` pre-route for input-required bodies, and
  an input-required result's embedded request entries must each have supplied
  ``method`` (the matching parse mandate);
- the ``"params"`` / ``"_meta"`` wire keys and the reserved
  ``io.modelcontextprotocol/*`` key constants — the required-`_meta` step on
  emission and the matching parse mandate.

Everything else reaches the engine as rows or block scalars.

Serialization is additive-only: emitted keys and leaf values always come
from the model's own dump, and nothing is ever removed from it. The fixed
order is refuse, dump, inject, required `_meta`. Refusals fire before the
dump so a refused value never half-emits; injections and the `_meta` step
apply to the top-level dump only and set keys that are absent, never
overwriting a present one. The surface block serving versions at or below
2025-11-25 carries no rows at all, so there the emitted body IS the plain
dump; embedded message bodies (request, notification, or result models
nested inside another body's fields, such as input-request/input-response
map values) pass through verbatim on every surface, and their hygiene is the
embedding caller's responsibility.

Parse order is fixed: result-union candidate selection (with the `resultType`
pre-route) ranks the structurally plausible arms best match first, superset
validation with the unknown-tag refinement tries them in that order (first
success wins; when all fail, the best-ranked arm's errors surface), then the
three version-keyed inbound mandates run (unrecognized `resultType`, embedded
input-request entries without `method`, required reserved `_meta` keys). The
`resultType` and `_meta` mandates read the RAW wire data, never a re-dump; the
input-request mandate reads the parsed entries' `model_fields_set`, which
records exactly the keys the raw data supplied. All mandates are skipped
entirely when the version is unknown (`facts` is None); the surface serving
versions at or below 2025-11-25 carries empty mandate scalars, so they are
equally inert there.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import UnionType
from typing import Any, TypeGuard, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from mcp.types import _types
from mcp.types._types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    EmptyResult,
    InputRequiredResult,
    Request,
    Result,
)
from mcp.types._version_facts import (
    Inject,
    SurfaceFacts,
    UnsupportedAtVersionError,
    missing_identity_meta,
)
from mcp.types.jsonrpc import JSONRPCError, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse

_ENVELOPE_TYPES = (JSONRPCRequest, JSONRPCNotification, JSONRPCResponse, JSONRPCError)

# Caches, populated on first use: one TypeAdapter per parse target, and one
# top-level wire-key set per model class (used by result-union member
# selection).
_ADAPTERS: dict[Any, TypeAdapter[Any]] = {}
_WIRE_KEYS: dict[type[BaseModel], frozenset[str]] = {}


def _dump(model: BaseModel) -> dict[str, Any]:
    """The plain user-level dump every transport uses; shaping edits a copy of it."""
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def _is_list(value: Any) -> TypeGuard[list[Any]]:
    """isinstance check that narrows a dynamic JSON value to a typed list."""
    return isinstance(value, list)


def _is_mapping(value: Any) -> TypeGuard[Mapping[str, Any]]:
    """isinstance check that narrows a dynamic JSON value to a typed mapping."""
    return isinstance(value, Mapping)


def serialize(model: BaseModel, version: str, facts: SurfaceFacts) -> dict[str, Any]:
    """Dump `model` and apply `facts`' emission rows, in the fixed order.

    Additive-only: emitted keys and values always come from the dump, plus
    the surface's inject-if-absent rows; nothing is ever removed. With the
    empty surface block (every version at or below 2025-11-25) every step
    below is a no-op and the plain dump is returned unchanged.
    """
    if isinstance(model, _ENVELOPE_TYPES):
        # Envelope shape is version-invariant; interiors (`params`/`result`)
        # are untyped dicts here and pass through opaque - payload shaping
        # happens when the payload is serialized as its typed model.
        return _dump(model)
    for refusal in facts.refuse_on_emit:
        if isinstance(model, refusal.owner) and (refusal.when is None or refusal.when(model)):
            raise UnsupportedAtVersionError(
                version, f"{refusal.because} cannot be represented at protocol version {version}"
            )
    dump = _dump(model)
    _inject(model, dump, facts.inject_on_emit)
    method = getattr(model, "method", None)
    if method in facts.meta_required_methods:
        _ensure_required_meta(model, dump, version, str(method))
    return dump


def _inject(model: BaseModel, dump: dict[str, Any], rows: tuple[Inject, ...]) -> None:
    """Set required-but-unset wire fields on the top-level dump only.

    When several rows name the same wire field (a base-class row plus a
    subclass row), the most-derived owner wins, so a subclass can carry its
    own value for a field its base would otherwise default. A row's `unless`
    classes are carved out of the owner's fan-out entirely.
    """
    mro = type(model).__mro__
    chosen: dict[str, Inject] = {}
    for row in rows:
        if not isinstance(model, row.owner) or isinstance(model, row.unless):
            continue
        current = chosen.get(row.wire_field)
        if current is None or mro.index(row.owner) < mro.index(current.owner):
            chosen[row.wire_field] = row
    for wire_field, row in chosen.items():
        dump.setdefault(wire_field, row.value)


def _ensure_required_meta(model: BaseModel, dump: dict[str, Any], version: str, method: str) -> None:
    """Materialize `params._meta` and supply the protocol version key.

    Injection merges: a user-set protocol version key is never overwritten.
    The two identity keys (client info and client capabilities) are
    caller-supplied — the boundary never synthesizes session identity — so
    their absence makes the request unsendable at this version.
    """
    params = dump.setdefault("params", {})
    meta = params.setdefault("_meta", {})
    meta.setdefault(PROTOCOL_VERSION_META_KEY, version)
    if missing_identity_meta(model):
        raise UnsupportedAtVersionError(
            version,
            f"a {method!r} request at protocol version {version} requires caller-supplied "
            f"{CLIENT_INFO_META_KEY!r} and {CLIENT_CAPABILITIES_META_KEY!r} keys in params._meta",
        )


def parse(type_: Any, data: Mapping[str, Any], version: str, facts: SurfaceFacts | None) -> Any:
    """Validate `data` as `type_`, applying `facts`' inbound mandates."""
    targets: tuple[Any, ...] = (type_,)
    arms = _result_union_arms(type_)
    if arms is not None:
        members = _select_result_members(arms, data, facts)
        if members:
            targets = members
    value = _validate_first(targets, data)
    if facts is not None:
        _apply_parse_mandates(value, data, version, facts)
    return value


def _apply_parse_mandates(value: Any, data: Mapping[str, Any], version: str, facts: SurfaceFacts) -> None:
    """Apply the version-keyed inbound mandates to a successfully parsed value."""
    title = type(value).__name__
    method = getattr(value, "method", None)
    if isinstance(value, Result) and facts.recognized_result_types:
        _check_result_type(data, facts.recognized_result_types, version, title)
    if isinstance(value, InputRequiredResult) and "input_required" in facts.recognized_result_types:
        _check_input_request_methods(value, title)
    if isinstance(value, Request) and method in facts.meta_required_methods:
        _check_required_meta(data, version, title)


def _result_union_arms(type_: Any) -> tuple[type[Result], ...] | None:
    """The arms of `type_` when it is a union made up entirely of `Result` subclasses."""
    if get_origin(type_) not in (Union, UnionType):
        return None
    arms = get_args(type_)
    if all(isinstance(arm, type) and issubclass(arm, Result) for arm in arms):
        return arms
    return None


def _select_result_members(
    arms: tuple[type[Result], ...], data: Mapping[str, Any], facts: SurfaceFacts | None
) -> tuple[type[Result], ...]:
    """Rank the result-union arms that could own `data`, best match first.

    An input-required body routes by its `resultType` value on versions that
    recognize it. Otherwise every arm recognizing strictly more of the
    payload's top-level wire keys than the base `Result` key set is a
    candidate, ranked by recognized-key count with ties kept in union
    declaration order; the caller validates candidates in rank order and the
    first success wins. Key counting cannot tell sibling arms with identical
    top-level key sets apart (single-content vs array-content sampling
    results differ only in the SHAPE of `content`), so a single pick would
    reject bodies that a later candidate accepts. With no candidate at all
    the body parses as the open-shaped `EmptyResult` arm, which would
    otherwise validate every JSON object and mask a better-matching member's
    validation failures. Returns () — parse the union as given — only when
    there is no candidate and no `EmptyResult` arm to fall back on.
    """
    if (
        facts is not None
        and "input_required" in facts.recognized_result_types
        and InputRequiredResult in arms
        and data.get("resultType") == "input_required"
    ):
        return (InputRequiredResult,)
    keys = frozenset(data)
    base_score = len(keys & _wire_keys(Result))
    scores = {arm: len(keys & _wire_keys(arm)) for arm in arms}
    candidates = sorted((arm for arm in arms if scores[arm] > base_score), key=lambda arm: -scores[arm])
    if candidates:
        return tuple(candidates)
    return (EmptyResult,) if EmptyResult in arms else ()


def _wire_keys(model_cls: type[BaseModel]) -> frozenset[str]:
    """The top-level wire keys (serialization aliases) `model_cls` recognizes."""
    keys = _WIRE_KEYS.get(model_cls)
    if keys is None:
        keys = frozenset(
            field.serialization_alias or field.alias or name for name, field in model_cls.model_fields.items()
        )
        _WIRE_KEYS[model_cls] = keys
    return keys


def _validate_first(targets: tuple[Any, ...], data: Mapping[str, Any]) -> Any:
    """Validate `data` against each target in order; the first success wins.

    When every target rejects, the surfaced error is the FIRST target's: the
    best-ranked candidate is the arm the payload most resembles, so its line
    errors (refined exactly like a single-target parse) describe the failure.
    """
    first, *rest = targets
    try:
        return _validate(first, data)
    except ValidationError:
        for target in rest:
            try:
                return _validate(target, data)
            except ValidationError:
                continue
        raise


def _validate(type_: Any, data: Mapping[str, Any]) -> Any:
    """One lenient superset parse, with unknown content tags refined.

    A plain (non-discriminated) union reports an unknown ``"type"`` tag as one
    failure per arm; the refinement re-raises those as a single
    `union_tag_invalid` error at the failing location so an unknown tag is
    distinguishable from a structurally invalid payload, at any nesting depth.
    """
    adapter = _ADAPTERS.get(type_)
    if adapter is None:
        adapter = _ADAPTERS[type_] = TypeAdapter(type_)
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        refined = _refine_unknown_tag(error, data)
        if refined is not None:
            raise refined from error
        raise


def _refine_unknown_tag(error: ValidationError, data: Mapping[str, Any]) -> ValidationError | None:
    """A `union_tag_invalid` error when a failing union input carries an unknown tag.

    Failing input fragments are located by walking each error location through
    `data`; location parts that do not index into the input are union-arm
    labels (pydantic inserts the arm name when a plain union fails). Where the
    fragment is a mapping whose ``"type"`` value is a string outside the tag
    set of the union's arms, the unknown tag - not the per-arm fallout - is
    the real failure. The arm labels are gathered from EVERY error line under
    a fragment, not only the tag mismatches: an arm whose tag matches fails
    elsewhere, and its presence proves the tag is known, so the failure is
    structural. Tag-less and structural failures return None and surface
    unchanged.
    """
    fragments: dict[tuple[str | int, ...], Mapping[str, Any]] = {}
    for line in error.errors():
        loc = line["loc"]
        if line["type"] != "literal_error" or not loc or loc[-1] != "type":
            continue
        located = _locate(loc[:-1], data)
        if located is None:
            continue
        path, _, fragment = located
        if _is_mapping(fragment) and isinstance(fragment.get("type"), str):
            fragments[path] = fragment
    if not fragments:
        return None
    labels_by_path: dict[tuple[str | int, ...], set[str]] = {path: set() for path in fragments}
    for line in error.errors():
        located = _locate(line["loc"], data)
        if located is None:
            continue
        path, labels, _ = located
        for fragment_path, fragment_labels in labels_by_path.items():
            if path[: len(fragment_path)] == fragment_path:
                fragment_labels.update(labels)
    for path, fragment in fragments.items():
        tags = _union_tags(labels_by_path[path])
        tag = fragment["type"]
        if tags and tag not in tags:
            line_error = InitErrorDetails(
                type=PydanticCustomError(
                    "union_tag_invalid",
                    "Input tag '{tag}' found using 'type' does not match any of the expected tags: {expected_tags}",
                    {"tag": tag, "expected_tags": ", ".join(repr(expected) for expected in sorted(tags))},
                ),
                loc=path,
                input=fragment,
            )
            return ValidationError.from_exception_data(error.title, [line_error])
    return None


def _locate(loc: tuple[str | int, ...], data: Mapping[str, Any]) -> tuple[tuple[str | int, ...], list[str], Any] | None:
    """Split an error location into its input path, arm labels, and fragment.

    Walks `loc` through `data`, consuming parts that index into the input and
    collecting the rest (union-arm labels) on the side. An integer part that
    does not index anything means the location does not resolve in this input;
    such errors are left for the caller to surface unchanged.
    """
    fragment: Any = data
    path: list[str | int] = []
    labels: list[str] = []
    for part in loc:
        if isinstance(part, str) and _is_mapping(fragment) and part in fragment:
            fragment = fragment[part]
            path.append(part)
        elif isinstance(part, int) and _is_list(fragment) and 0 <= part < len(fragment):
            fragment = fragment[part]
            path.append(part)
        elif isinstance(part, str):
            labels.append(part)
        else:
            return None
    return tuple(path), labels, fragment


def _union_tags(labels: list[str] | set[str]) -> frozenset[str]:
    """The ``"type"`` literal values of the `mcp.types._types` classes named by `labels`.

    Labels that name no class in `mcp.types._types` (synthetic pydantic labels
    such as ``list[union[...]]``) and classes without a literal ``type`` field
    contribute nothing.
    """
    tags: set[str] = set()
    for label in labels:
        member = getattr(_types, label, None)
        if isinstance(member, type) and issubclass(member, BaseModel):
            field = member.model_fields.get("type")
            if field is not None:
                tags.update(tag for tag in get_args(field.annotation) if isinstance(tag, str))
    return frozenset(tags)


def _check_result_type(data: Mapping[str, Any], recognized: frozenset[str], version: str, title: str) -> None:
    """Reject a present-and-unrecognized raw `resultType` value.

    An absent value is always accepted (the spec defines absence as
    equivalent to "complete"); a recognized value is retained as parsed.
    """
    value = data.get("resultType")
    if value is None or value in recognized:
        return
    line_error = InitErrorDetails(
        type=PydanticCustomError(
            "result_type_invalid",
            "unrecognized resultType {result_type}; protocol version {version} recognizes: {recognized}",
            {"result_type": value, "version": version, "recognized": ", ".join(sorted(recognized))},
        ),
        loc=("resultType",),
        input=value,
    )
    raise ValidationError.from_exception_data(title, [line_error])


def _check_input_request_methods(result: InputRequiredResult, title: str) -> None:
    """Reject embedded input-request entries that did not supply `method`.

    The values of an input-required result's `inputRequests` map are full
    request payloads, and the schema requires `method` on every request. The
    request models default their method literal (so handler code can construct
    them without boilerplate), which lets a method-less entry quietly validate
    as the one member whose remaining fields are all optional; the mandate
    instead checks that every entry actually supplied the field. A missing
    `method` is a structural failure (plain `missing` line error at the
    entry's own method key), not an unknown union member.
    """
    if result.input_requests is None:
        return
    line_errors = [
        InitErrorDetails(type="missing", loc=("inputRequests", key, "method"), input=None)
        for key, entry in result.input_requests.items()
        if "method" not in entry.model_fields_set
    ]
    if line_errors:
        raise ValidationError.from_exception_data(title, line_errors)


def _check_required_meta(data: Mapping[str, Any], version: str, title: str) -> None:
    """Reject a request whose raw `params._meta` lacks any reserved key.

    Each of the three keys is independently required: every missing key gets
    its own line error, so a partial `_meta`, an empty one, and a missing
    container all report exactly what is absent.
    """
    params = data.get("params")
    meta = params.get("_meta") if _is_mapping(params) else None
    present: Mapping[str, Any] = meta if _is_mapping(meta) else {}
    line_errors = [
        InitErrorDetails(
            type=PydanticCustomError(
                "missing_required_meta",
                "request params._meta must carry {meta_key} at protocol version {version}",
                {"meta_key": key, "version": version},
            ),
            loc=("params", "_meta", key),
            input=dict(present),
        )
        for key in (PROTOCOL_VERSION_META_KEY, CLIENT_INFO_META_KEY, CLIENT_CAPABILITIES_META_KEY)
        if key not in present
    ]
    if line_errors:
        raise ValidationError.from_exception_data(title, line_errors)
