"""Cross-check the wire-surface fact blocks against the generated spec oracles.

The two `SurfaceFacts` blocks in `mcp.types._version_facts` are hand-written;
the generated oracle modules (`tests/spec_oracles`, pinned at spec commit
6d441518) are the machine-derived witnesses. These tests check every inject
row of the 2026-07-28 block against draft-oracle field presence, requiredness
and value typing (including the carve-outs for the definitions the schema
leaves the field off), tie each refusal to the schema fact behind it — the
type-level refusals must equal exactly the monolith body types the draft
schema does not define — re-derive the two mandate scalars, and pin the
emptiness of the block serving 2025-11-25 and earlier.

The block serving 2025-11-25 and earlier is ONE surface for FOUR pinned
schemas, which is only sound if those schemas evolved strictly additively.
The additive-coverage proof at the bottom asserts exactly that, oracle by
oracle: every definition and field of the 2024-11-05, 2025-03-26, and
2025-06-18 oracles must be present on the 2025-11-25 oracle with an
equal-or-wider shape. A definition absent there would falsify the premise
and must surface as a hard failure, never a tolerance entry.

The per-version method tables are checked against the oracles in
`tests/types/test_version_registry.py`.
"""

from collections.abc import Mapping
from types import ModuleType, UnionType
from typing import Annotated, Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel, TypeAdapter
from typing_extensions import TypeAliasType

import mcp.types
from mcp.types import Notification, Request, Result
from mcp.types._version_facts import (
    SURFACE_FACTS,
    V2025_11_25,
    V2026_07_28,
    Inject,
    Refuse,
    _empty_input_required,
)
from tests.spec_oracles import v2024_11_05, v2025_03_26, v2025_06_18, v2025_11_25, v2026_07_28
from tests.spec_oracles._harness import compat, resolve_sdk_name, sdk_lookup, sig, wire_fields

ORACLE_BY_VERSION: dict[str, ModuleType] = {
    "2024-11-05": v2024_11_05,
    "2025-03-26": v2025_03_26,
    "2025-06-18": v2025_06_18,
    "2025-11-25": v2025_11_25,
    "2026-07-28": v2026_07_28,
}

# Oracle definition name -> SDK class name, for capability sub-objects the
# schemas declare inline and the SDK names with a Capability suffix.
LIFTED_DEF_NAMES = {"Roots": "RootsCapability"}


def oracle_model_defs(oracle: ModuleType) -> dict[str, type[BaseModel]]:
    """Every model definition the oracle module itself declares."""
    return {
        name: obj
        for name, obj in vars(oracle).items()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == oracle.__name__
    }


def oracle_counterparts(version: str, owner: type[BaseModel]) -> dict[str, type[BaseModel]]:
    """The oracle definitions at `version` whose SDK counterpart is `owner` or a subclass."""
    oracle = ORACLE_BY_VERSION[version]
    oracle_key = oracle.__name__.rsplit(".", 1)[-1]
    counterparts: dict[str, type[BaseModel]] = {}
    for def_name, oracle_cls in oracle_model_defs(oracle).items():
        sdk_name = LIFTED_DEF_NAMES.get(def_name, resolve_sdk_name(oracle_key, def_name))
        sdk_obj = sdk_lookup(sdk_name)
        if isinstance(sdk_obj, type) and issubclass(sdk_obj, owner):
            counterparts[def_name] = oracle_cls
    return counterparts


def counterpart_sdk_class(def_name: str) -> type[BaseModel]:
    sdk_obj = sdk_lookup(LIFTED_DEF_NAMES.get(def_name, resolve_sdk_name("v2026_07_28", def_name)))
    assert isinstance(sdk_obj, type) and issubclass(sdk_obj, BaseModel)
    return sdk_obj


# ----------------------------------------------------------------------------
# The block serving 2025-11-25 and earlier.
# ----------------------------------------------------------------------------


def test_the_surface_serving_2025_11_25_and_earlier_is_empty() -> None:
    """Emission at or below 2025-11-25 is the plain monolith dump and parsing
    is the plain superset parse: the block carries no rows and no mandate
    scalars. No schema at or below 2025-11-25 defines a required field the
    dump can lack (checked per version by the mandate-scalar tests below),
    and the absence of every other row kind is the additive-boundary stance:
    deployed peers ignore unknown keys, and gating newer constructs by
    negotiated version or capability is session-layer work."""
    assert V2025_11_25.inject_on_emit == ()
    assert V2025_11_25.refuse_on_emit == ()
    assert V2025_11_25.meta_required_methods == frozenset()
    assert V2025_11_25.recognized_result_types == frozenset()


# ----------------------------------------------------------------------------
# Inject rows vs the draft oracle. An inject row says "this surface's wire
# requires the field": resolve the row's owner to its draft oracle
# definition(s) — base-class owners fan out to every definition whose SDK
# counterpart subclasses the owner, the same isinstance reach the rows have at
# runtime — and check the field is present and required there, and that the
# injected default satisfies the oracle's field type. Definitions covered by
# the row's `unless` carve-out must instead LACK the field: the carve-out
# exists exactly where the schema leaves the field off.
# ----------------------------------------------------------------------------


def inject_row_ids(row: Inject) -> str:
    return f"{row.owner.__name__}.{row.wire_field}"


@pytest.mark.parametrize("row", V2026_07_28.inject_on_emit, ids=inject_row_ids)
def test_inject_rows_match_the_draft_oracle(row: Inject) -> None:
    counterparts = oracle_counterparts("2026-07-28", row.owner)
    assert counterparts, f"inject row {row.owner.__name__}.{row.wire_field} has no oracle definition"
    for def_name, oracle_cls in counterparts.items():
        fields = wire_fields(oracle_cls)
        if row.unless and issubclass(counterpart_sdk_class(def_name), row.unless):
            assert row.wire_field not in fields, f"{def_name} carries {row.wire_field}; carve-out is wrong"
            continue
        assert row.wire_field in fields, f"{def_name} lacks {row.wire_field}"
        assert fields[row.wire_field].is_required(), f"{def_name}.{row.wire_field} is optional"
        TypeAdapter(fields[row.wire_field].annotation).validate_python(row.value)


def test_result_type_carve_out_covers_both_halves_of_the_sampling_split() -> None:
    """The SDK splits the schema's single CreateMessageResult into a narrow
    single-block class and an array/tool-content class. The schema definition
    carries no resultType, so the carve-out must name both SDK halves."""
    (row,) = [r for r in V2026_07_28.inject_on_emit if r.wire_field == "resultType" and r.owner is Result]
    assert mcp.types.CreateMessageResult in row.unless
    assert mcp.types.CreateMessageResultWithTools in row.unless


# ----------------------------------------------------------------------------
# Refuse rows vs the schema facts behind them.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("version", SURFACE_FACTS)
def test_empty_input_required_refusal_matches_oracle(version: str) -> None:
    """The at-least-one-of check exists exactly where the schema defines the type.

    The 2026-07-28 schema requires at least one of inputRequests/requestState
    in prose only — both fields are optional in the schema — which is why the
    fact is an emission check and not model validation.
    """
    rows = [row for row in SURFACE_FACTS[version].refuse_on_emit if row.when is _empty_input_required]
    schema_type = oracle_model_defs(ORACLE_BY_VERSION[version]).get("InputRequiredResult")
    if schema_type is None:
        assert rows == []
    else:
        assert [row.owner for row in rows] == [mcp.types.InputRequiredResult]
        assert not wire_fields(schema_type)["inputRequests"].is_required()
        assert not wire_fields(schema_type)["requestState"].is_required()


def type_floor_row_ids(row: Refuse) -> str:
    return row.owner.__name__


TYPE_FLOOR_ROWS = tuple(row for row in V2026_07_28.refuse_on_emit if row.when is None)


def draft_covered_sdk_names() -> frozenset[str]:
    """The SDK class names the 2026-07-28 schema defines a wire shape for.

    `CreateMessageResultWithTools` rides the schema's single CreateMessageResult
    definition (the SDK-side split, recorded in `mcp.types._spec_names`).
    """
    names = {
        LIFTED_DEF_NAMES.get(def_name, resolve_sdk_name("v2026_07_28", def_name))
        for def_name in oracle_model_defs(v2026_07_28)
    }
    assert "CreateMessageResult" in names
    names.add("CreateMessageResultWithTools")
    return frozenset(names)


def test_type_floor_refusals_equal_the_bodies_absent_from_the_draft_schema() -> None:
    """A type-level refusal exists exactly for the public message-body classes
    the 2026-07-28 schema does not define: the removed lifecycle, logging,
    per-URI subscription, and roots list_changed messages, plus the
    2025-11-25 task types (tasks continue as an extension). Equality in both
    directions: a missing row would emit a guessed shape, an extra row would
    refuse a legal value."""
    covered = draft_covered_sdk_names()
    absent_bodies = {
        name
        for name in mcp.types.__all__
        if isinstance(obj := getattr(mcp.types, name), type)
        and issubclass(obj, BaseModel)
        and issubclass(obj, Request | Notification | Result)
        and name not in covered
    }
    assert {row.owner.__name__ for row in TYPE_FLOOR_ROWS} == absent_bodies


@pytest.mark.parametrize("row", TYPE_FLOOR_ROWS, ids=type_floor_row_ids)
def test_type_floor_rows_do_not_reach_subclasses_with_a_draft_shape(row: Refuse) -> None:
    """Refuse rows match by isinstance; none of the refused classes may have a
    draft-defined subclass that the fan-out would wrongly catch."""
    covered = draft_covered_sdk_names()
    for name in covered:
        sdk_obj = sdk_lookup(name)
        if isinstance(sdk_obj, type):
            assert not issubclass(sdk_obj, row.owner), f"{name} would be wrongly refused via {row.owner.__name__}"


# ----------------------------------------------------------------------------
# Mandate scalars vs the oracles, per served version.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("version", SURFACE_FACTS)
def test_meta_required_methods_match_oracle(version: str) -> None:
    """The required-_meta method set equals the requests whose params require the
    reserved keys at the served version.

    Only the 2026-07-28 schema defines RequestMetaObject (the params `_meta`
    shape carrying the required reserved keys), and it requires it on every
    client request: each arm's params declare a required RequestMetaObject
    `_meta`, asserted arm by arm. Every other version derives the empty set,
    which is what the shared block serving them carries.
    """
    oracle = ORACLE_BY_VERSION[version]
    request_meta = getattr(oracle, "RequestMetaObject", None)
    derived: set[str] = set()
    if request_meta is not None:
        for arm in get_args(oracle.ClientRequest):
            (method,) = get_args(arm.model_fields["method"].annotation)
            params = arm.model_fields["params"].annotation
            assert isinstance(params, type) and issubclass(params, BaseModel), f"{method} params must be a model"
            meta_field = wire_fields(params)["_meta"]
            assert meta_field.is_required() and meta_field.annotation is request_meta, (
                f"{method} params must require a RequestMetaObject _meta"
            )
            derived.add(method)
    assert SURFACE_FACTS[version].meta_required_methods == frozenset(derived)


@pytest.mark.parametrize("version", SURFACE_FACTS)
def test_recognized_result_types_match_oracle(version: str) -> None:
    """Recognized resultType values exist exactly where the schema defines ResultType.

    The 2026-07-28 schema types ResultType as an open string and names exactly
    two values, "complete" and "input_required", in its description; earlier
    schemas have no ResultType at all, so any inbound value parses there.
    """
    oracle = ORACLE_BY_VERSION[version]
    if hasattr(oracle, "ResultType"):
        assert oracle.ResultType is str
        assert SURFACE_FACTS[version].recognized_result_types == frozenset({"complete", "input_required"})
    else:
        assert SURFACE_FACTS[version].recognized_result_types == frozenset()


# ----------------------------------------------------------------------------
# Additive-coverage proof: one surface block serves the four schemas at or
# below 2025-11-25 only because their evolution is strictly additive. For
# every definition of the 2024-11-05, 2025-03-26, and 2025-06-18 oracles, the
# 2025-11-25 oracle must define the same construct with every old field
# present, nothing newly required, and an equal-or-wider shape per field.
#
# Three rendering facts of the pinned schemas (6d441518) shape the walk:
#
# - The 2025-11-25 schema folds the JSON-RPC frame keys (`jsonrpc`, `id`)
#   into each request/notification definition; earlier schemas keep them on
#   the envelope definitions only. Frame keys are version-invariant envelope
#   facts (modeled in `mcp.types.jsonrpc`) and are excluded from the field
#   walk, as are the envelope definitions themselves — including the one
#   genuine intra-line removal, the 2025-03-26-only batch frames, which is
#   an envelope fact, not a type-surface fact.
# - The generators synthesize local names for inline objects (request params,
#   capability sub-objects), and the numbering differs per version, so
#   definitions pair by their resolved SDK name and synthetic models pair
#   structurally inside their parent's fields.
# - Older schemas render some capability objects as open dicts where
#   2025-11-25 names a definition; an open dict's payloads are arbitrary
#   objects, which a model with no required fields accepts wholesale.
# ----------------------------------------------------------------------------

OLD_ORACLES = ("v2024_11_05", "v2025_03_26", "v2025_06_18")
ENVELOPE_DEF_NAMES = frozenset(
    {
        "JSONRPCRequest",
        "JSONRPCNotification",
        "JSONRPCResponse",
        "JSONRPCError",
        "JSONRPCMessage",
        "JSONRPCBatchRequest",
        "JSONRPCBatchResponse",
    }
)
ENVELOPE_KEYS = frozenset({"jsonrpc", "id"})


def _unwrap(annotation: Any) -> Any:
    """Strip Annotated wrappers and type aliases down to the bare annotation."""
    while True:
        origin = get_origin(annotation)
        if origin is not None and str(origin) == "typing.Annotated":
            annotation = get_args(annotation)[0]
            continue
        if isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__
            continue
        return annotation


def _members(annotation: Any) -> list[Any]:
    """The flattened union members of an annotation (itself, if not a union)."""
    annotation = _unwrap(annotation)
    if get_origin(annotation) in (Union, UnionType):
        members: list[Any] = []
        for arm in get_args(annotation):
            members.extend(_members(arm))
        return members
    return [annotation]


def _is_model(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseModel)


def _is_open_dict(annotation: Any) -> bool:
    annotation = _unwrap(annotation)
    if get_origin(annotation) is dict:
        args = get_args(annotation)
        return not args or _unwrap(args[1]) is Any
    return False


def _no_required_fields(model_cls: type[BaseModel]) -> bool:
    return all(not info.is_required() for info in wire_fields(model_cls).values())


def _model_pair_problems(
    old_cls: type[BaseModel],
    new_cls: type[BaseModel],
    oracle_key: str,
    path: str,
    seen: frozenset[tuple[type[BaseModel], type[BaseModel]]],
) -> list[str]:
    """Coverage problems for an (old definition, 2025-11-25 definition) pair."""
    pair = (old_cls, new_cls)
    if pair in seen:
        return []
    seen = seen | {pair}
    old_fields, new_fields = wire_fields(old_cls), wire_fields(new_cls)
    problems = [
        f"{oracle_key} {path}.{wire_name}: field absent at 2025-11-25"
        for wire_name in old_fields
        if wire_name not in ENVELOPE_KEYS and wire_name not in new_fields
    ]
    problems += [
        f"{oracle_key} {path}.{wire_name}: newly required at 2025-11-25"
        for wire_name, info in new_fields.items()
        if wire_name not in ENVELOPE_KEYS
        and info.is_required()
        and (wire_name not in old_fields or not old_fields[wire_name].is_required())
    ]
    for wire_name, info in old_fields.items():
        if wire_name in ENVELOPE_KEYS or wire_name not in new_fields:
            continue
        problems += _union_problems(
            info.annotation, new_fields[wire_name].annotation, oracle_key, f"{path}.{wire_name}", seen
        )
    return problems


def _member_trial(
    old_member: Any,
    new_member: Any,
    oracle_key: str,
    path: str,
    seen: frozenset[tuple[type[BaseModel], type[BaseModel]]],
) -> list[str] | None:
    """Problems if `new_member` is tried as the cover of `old_member`; None when
    the pair cannot be related at all."""
    if _is_model(old_member) and _is_model(new_member):
        old_name = resolve_sdk_name(oracle_key, old_member.__name__)
        new_name = resolve_sdk_name("v2025_11_25", new_member.__name__)
        if old_name == new_name or sdk_lookup(old_name) is None or sdk_lookup(new_name) is None:
            return _model_pair_problems(
                old_member, new_member, oracle_key, f"{path}<{old_member.__name__}~{new_member.__name__}>", seen
            )
        return None
    if _is_model(old_member) and _is_open_dict(new_member):
        return []
    if _is_open_dict(old_member) and _is_model(new_member):
        return [] if _no_required_fields(new_member) else None
    if _is_model(old_member) or _is_model(new_member):
        return None
    old_origin = get_origin(_unwrap(old_member))
    new_origin = get_origin(_unwrap(new_member))
    if old_origin is list and new_origin is list:
        old_args, new_args = get_args(_unwrap(old_member)), get_args(_unwrap(new_member))
        return _union_problems(
            old_args[0] if old_args else Any, new_args[0] if new_args else Any, oracle_key, f"{path}[]", seen
        )
    if old_origin is dict and new_origin is dict:
        old_args, new_args = get_args(_unwrap(old_member)), get_args(_unwrap(new_member))
        return _union_problems(
            old_args[1] if old_args else Any, new_args[1] if new_args else Any, oracle_key, f"{path}{{}}", seen
        )
    relation = compat(sig(old_member, sdk=False), sig(new_member, sdk=False))
    return [] if relation in ("equal", "sdk_wider") else None


def _union_problems(
    old_annotation: Any,
    new_annotation: Any,
    oracle_key: str,
    path: str,
    seen: frozenset[tuple[type[BaseModel], type[BaseModel]]],
) -> list[str]:
    """Every old union member must be covered by some 2025-11-25 member."""
    new_members = _members(new_annotation)
    problems: list[str] = []
    for old_member in _members(old_annotation):
        if old_member is type(None) and any(member is type(None) for member in new_members):
            continue
        trials = [
            trial
            for member in new_members
            if (trial := _member_trial(old_member, member, oracle_key, path, seen)) is not None
        ]
        if any(not trial for trial in trials):
            continue
        if trials:
            problems += min(trials, key=len)
        else:
            problems.append(f"{oracle_key} {path}: old member {old_member!r} has no cover at 2025-11-25")
    return problems


def _oracle_coverage_problems(
    old_defs: Mapping[str, type[BaseModel]],
    oracle_key: str,
    new_by_sdk_name: Mapping[str, type[BaseModel]],
) -> list[str]:
    """The full coverage walk of one older oracle against the 2025-11-25 defs."""
    problems: list[str] = []
    for def_name, def_cls in sorted(old_defs.items()):
        if def_name in ENVELOPE_DEF_NAMES:
            continue
        sdk_name = resolve_sdk_name(oracle_key, def_name)
        if sdk_lookup(sdk_name) is None:
            # Synthetic inline-object names and deliberately not-modeled
            # definitions (the elicitation requested-schema vocabulary) have
            # no SDK anchor; the synthetic ones are still walked structurally
            # through their parents' fields.
            continue
        new_cls = new_by_sdk_name.get(sdk_name)
        if new_cls is None:
            problems.append(f"{oracle_key} {def_name}: definition absent at 2025-11-25 (sdk name {sdk_name})")
            continue
        problems += _model_pair_problems(def_cls, new_cls, oracle_key, def_name, frozenset())
    return problems


@pytest.mark.parametrize("oracle_key", OLD_ORACLES)
def test_2025_11_25_oracle_covers_each_older_oracle(oracle_key: str) -> None:
    """The additive premise, proven: every named definition of the older oracle
    pairs with a 2025-11-25 definition of the same resolved SDK name, and the
    pair (with everything reachable through its fields) has every old field
    present, nothing newly required, and equal-or-wider shapes. Any problem
    here falsifies serving this oracle's version from the 2025-11-25 surface
    and must be escalated, never tolerated away."""
    old_defs = oracle_model_defs(
        {"v2024_11_05": v2024_11_05, "v2025_03_26": v2025_03_26, "v2025_06_18": v2025_06_18}[oracle_key]
    )
    new_by_sdk_name: dict[str, type[BaseModel]] = {}
    for def_name, def_cls in oracle_model_defs(v2025_11_25).items():
        new_by_sdk_name.setdefault(resolve_sdk_name("v2025_11_25", def_name), def_cls)
    problems = _oracle_coverage_problems(old_defs, oracle_key, new_by_sdk_name)
    assert problems == [], "\n".join(problems)


# ----------------------------------------------------------------------------
# Self-tests of the coverage walk. The real oracles ARE additive, so the
# walk's report paths never fire above; synthetic definition pairs prove the
# proof can actually fail.
# ----------------------------------------------------------------------------


def test_coverage_walk_reports_an_absent_definition() -> None:
    old_defs = {"PingRequest": oracle_model_defs(v2024_11_05)["PingRequest"]}
    problems = _oracle_coverage_problems(old_defs, "v2024_11_05", {})
    assert problems == ["v2024_11_05 PingRequest: definition absent at 2025-11-25 (sdk name PingRequest)"]


def test_coverage_walk_reports_missing_and_newly_required_fields() -> None:
    class OldThing(BaseModel):
        kept: str
        gone: int | None = None

    class NewThing(BaseModel):
        kept: str
        fresh: bool

    problems = _model_pair_problems(OldThing, NewThing, "v2024_11_05", "Thing", frozenset())
    assert problems == [
        "v2024_11_05 Thing.gone: field absent at 2025-11-25",
        "v2024_11_05 Thing.fresh: newly required at 2025-11-25",
    ]


def test_coverage_walk_surfaces_nested_problems_of_the_best_structural_pair() -> None:
    """When no union member covers an old member cleanly, the closest
    structural pairing's nested problems surface."""

    class OldInner(BaseModel):
        value: str

    class NewInner(BaseModel):
        other: str

    class OldOuter(BaseModel):
        part: OldInner

    class NewOuter(BaseModel):
        part: NewInner

    problems = _model_pair_problems(OldOuter, NewOuter, "v2024_11_05", "Outer", frozenset())
    assert problems == [
        "v2024_11_05 Outer.part<OldInner~NewInner>.value: field absent at 2025-11-25",
        "v2024_11_05 Outer.part<OldInner~NewInner>.other: newly required at 2025-11-25",
    ]


def test_coverage_walk_handles_recursive_definitions() -> None:
    class OldNode(BaseModel):
        next_node: "OldNode | None" = None

    class NewNode(BaseModel):
        next_node: "NewNode | None" = None

    assert _model_pair_problems(OldNode, NewNode, "v2024_11_05", "Node", frozenset()) == []


_ALIASED = TypeAliasType("_ALIASED", Annotated[int, "marker"])


def test_unwrap_strips_annotated_and_alias_layers() -> None:
    assert _unwrap(Annotated[_ALIASED, "outer"]) is int
