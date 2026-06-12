"""Pin every committed version-package definition against its spec oracle.

The packages under ``src/mcp/types/v*`` are generated-then-hand-validated
source; the oracle modules under ``tests/spec_oracles`` are regenerated
verbatim from the pinned schemas. This test compares the two per version —
definition sets in both directions, and per model the wire aliases,
requiredness, and a normalized form of every field annotation — so a hand
edit that drifts from the pinned schema fails here.

The deliberate scaffold-pass deltas are the annotated tolerance tables below;
everything else must match exactly. Two deltas need no tolerance entry:
inheritance flattening (pydantic's ``model_fields`` already includes
inherited fields on the oracle side, so flattened package classes compare
equal), and the deterministic synthetic class names (derived from the oracle
in ``_synthetic_renames``, mirroring the scaffold pass).
"""

from __future__ import annotations

import importlib
import re
from types import ModuleType, UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import pytest
from pydantic import BaseModel, create_model
from typing_extensions import TypeAliasType

VERSIONS = (
    "v2024_11_05",
    "v2025_03_26",
    "v2025_06_18",
    "v2025_11_25",
    "v2026_07_28",
)

# Tolerance: value-transforming pydantic types are downgraded to plain ``str``
# in the packages — URL normalization and base64 re-encoding would change wire
# bytes on a validate -> re-dump round trip. (``Base64Str`` needs no entry: it
# is ``Annotated[str, ...]``, so both sides already compare as ``str``.)
_VALUE_DOWNGRADES = {"AnyUrl": "str", "FileUrl": "str"}

# Tolerance: the packages widen ``structuredContent`` from ``dict[str, Any]``
# to ``Any`` — the newest schema types the field ``Any``, and the wire models
# never narrow a value the SDK models accept.
_WIDENED_FIELDS = frozenset({"structured_content"})

# Tolerance: the pinned 2026-07-28 schema.json renders JSONValue's primitive
# branch as ["string", "integer", "boolean"], but its schema.ts source defines
# all six JSON types (string | number | boolean | null | object | array). The
# oracle reproduces the render verbatim; the package follows the schema.ts
# definition so fractional numbers and nulls validate. The package alias is
# pinned here verbatim, so any further drift still fails.
_ALIAS_OVERRIDES: dict[tuple[str, str], str] = {
    ("v2026_07_28", "JSONValue"): "JSONObject | list[JSONValue] | str | int | float | bool | None",
}

# Tolerance: content blocks carried into packages older than the schema that
# introduces them, so emitting such a block to an older peer passes it through
# instead of refusing. Maps package -> {class name -> introducing oracle};
# the carried class text is pinned against that oracle in
# test_carried_content_block_matches_introducing_version.
CARRIED_CONTENT_BLOCKS: dict[str, dict[str, str]] = {
    "v2024_11_05": {"AudioContent": "v2025_03_26", "ResourceLink": "v2025_06_18"},
    "v2025_03_26": {"ResourceLink": "v2025_06_18"},
}

# Tolerance: the pinned schema.json renderings type a few schema.ts `number`
# positions as "integer" — the same render artifact fixed for the JSONValue
# alias. The packages keep the int arm and gain a float arm at exactly these
# positions, so fractional elicitation answers and number-schema bounds have a
# wire form; the generated oracles keep the render verbatim, and the package
# annotation is pinned here verbatim so any further drift still fails.
# Position -> the exact package annotation.
_RENDER_ARTIFACT_WIDENED: dict[tuple[str, str, str], Any] = {
    ("v2025_06_18", "ElicitResult", "content"): dict[str, str | int | float | bool] | None,
    ("v2025_06_18", "NumberSchema", "maximum"): int | float | None,
    ("v2025_06_18", "NumberSchema", "minimum"): int | float | None,
    ("v2025_11_25", "ElicitResult", "content"): dict[str, list[str] | str | int | float | bool] | None,
    ("v2025_11_25", "NumberSchema", "default"): int | float | None,
    ("v2025_11_25", "NumberSchema", "maximum"): int | float | None,
    ("v2025_11_25", "NumberSchema", "minimum"): int | float | None,
    ("v2026_07_28", "ElicitResult", "content"): dict[str, list[str] | str | int | float | bool] | None,
}

# The closure for every OTHER package field that admits int but not float:
# the integer rendering is the intended type, justified per field name by the
# spec fact in plain words. A field name absent here whose annotation is
# int-without-float fails test_int_only_number_positions_are_classified, so a
# future render artifact cannot land unexamined.
_INTENDED_INTEGER_FIELDS: dict[str, str] = {
    "id": "JSON-RPC ids: every schema rendering pins the numeric kind to integer; fractional ids are not interoperable",
    "request_id": "a cancelled/targeted request id mirrors the JSON-RPC id type (string or integer)",
    "progress_token": "progress tokens mirror the JSON-RPC id type (string or integer)",
    "code": "JSON-RPC 2.0 defines error codes as integers",
    "total": "a count of completion values; the superset model agrees (int)",
    "max_tokens": "a token count; the superset model agrees (int)",
    "size": "a resource size in bytes; the superset model agrees (int)",
    "ttl": "a task time-to-live in milliseconds; the superset model agrees (int)",
    "ttl_ms": "a cache time-to-live in milliseconds; the superset model agrees (int)",
    "poll_interval": "a polling interval in milliseconds; the superset model agrees (int)",
    "max_length": "JSON Schema maxLength is a non-negative integer keyword",
    "min_length": "JSON Schema minLength is a non-negative integer keyword",
    "max_items": "JSON Schema maxItems is a non-negative integer keyword",
    "min_items": "JSON Schema minItems is a non-negative integer keyword",
}

# The expected-open class policy: every package class is ``extra="ignore"``
# except the ``_meta`` carriers (unknown ``_meta`` keys must survive
# revalidation), the tool input/output schema interiors (schema keywords
# beyond the declared properties ride extra fields), and the subscription
# filter (extensible on the wire). The first two groups are derived from the
# package's own field references in test_extra_policy.
_OPEN_INTERIOR_ALIASES = frozenset({"inputSchema", "outputSchema"})

# Names a module's import block binds; everything else public is a definition.
_IMPORTED_NAMES = frozenset(
    {
        "annotations",
        "Annotated",
        "Any",
        "Literal",
        "TypeAlias",
        "TypeAliasType",
        "AnyUrl",
        "Base64Str",
        "ConfigDict",
        "Field",
        "OracleModel",
        "WireModel",
        "OpenWireModel",
        "SPEC_DEFS",
    }
)

Sig = tuple[Any, ...]


def _package(version: str) -> ModuleType:
    return importlib.import_module(f"mcp.types.{version}")


def _oracle(version: str) -> ModuleType:
    return importlib.import_module(f"tests.spec_oracles.{version}")


def _module_defs(mod: ModuleType) -> dict[str, Any]:
    """Public names a module defines (classes and type aliases)."""
    return {name: obj for name, obj in vars(mod).items() if not name.startswith("_") and name not in _IMPORTED_NAMES}


def _module_classes(mod: ModuleType) -> dict[str, type[BaseModel]]:
    """Model classes a module defines, keyed by class name (aliases excluded)."""
    return {
        name: obj
        for name, obj in vars(mod).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == mod.__name__
        and obj.__name__ == name
    }


def _model_names_in(annotation: Any) -> frozenset[str]:
    """Names of model classes appearing anywhere in an annotation."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return frozenset({annotation.__name__})
    names: set[str] = set()
    for arg in get_args(annotation):
        names.update(_model_names_in(arg))
    return frozenset(names)


def _synthetic_renames(oracle: ModuleType) -> dict[str, str]:
    """Oracle synthetic class name -> package class name.

    Mirrors the scaffold's deterministic-naming pass: a generated
    ``Params<n>``/``Meta<n>`` class referenced by exactly one field of one
    owner is named ``<Owner>Params``/``<Owner>Meta`` in the package; shared
    synthetics keep their generated names.
    """
    classes = _module_classes(oracle)
    synthetic = {name for name in classes if re.fullmatch(r"(?:Params|Meta)\d*", name)}
    references: dict[str, list[tuple[str, str]]] = {name: [] for name in synthetic}
    for owner_name, cls in classes.items():
        for field_name, info in cls.model_fields.items():
            for name in synthetic & _model_names_in(info.annotation):
                references[name].append((owner_name, field_name))
    renames: dict[str, str] = {}
    taken = set(classes)
    for name in sorted(synthetic):
        refs = references[name]
        if len(refs) != 1:
            continue
        owner, field_name = refs[0]
        suffix = {"params": "Params", "meta": "Meta"}.get(field_name)
        if suffix is None:
            continue
        target = f"{owner}{suffix}"
        if target in taken:
            continue
        renames[name] = target
        taken.add(target)
    return renames


def _sig(annotation: Any, *, rename: dict[str, str], drop: frozenset[str], widen_dicts: bool = False) -> Sig:
    """Canonicalize an annotation into a comparable signature tuple.

    Classes appear by name (mapped through ``rename``), unions as unordered
    member sets. ``drop`` removes the carried content-block arms from package
    unions; ``widen_dicts`` collapses ``dict[str, Any]`` to ``Any`` for the
    widened-field tolerance.
    """
    if annotation is None or annotation is type(None):
        return ("none",)
    if annotation is Any:
        return ("any",)
    if isinstance(annotation, TypeAliasType):
        return ("aliasref", annotation.__name__)
    origin = get_origin(annotation)
    if origin is Annotated:
        return _sig(get_args(annotation)[0], rename=rename, drop=drop, widen_dicts=widen_dicts)
    if origin is Literal:
        return ("literal", frozenset(get_args(annotation)))
    if origin is Union or origin is UnionType:
        members = frozenset(
            _sig(arg, rename=rename, drop=drop, widen_dicts=widen_dicts)
            for arg in get_args(annotation)
            if not (isinstance(arg, type) and arg.__name__ in drop)
        )
        if len(members) == 1:
            return next(iter(members))
        return ("union", members)
    if origin is dict:
        key, value = (_sig(arg, rename=rename, drop=drop, widen_dicts=widen_dicts) for arg in get_args(annotation))
        if widen_dicts and key == ("cls", "str") and value == ("any",):
            return ("any",)
        return ("dict", key, value)
    if origin is not None:
        args = tuple(_sig(arg, rename=rename, drop=drop, widen_dicts=widen_dicts) for arg in get_args(annotation))
        return ("generic", origin.__name__, args)
    if isinstance(annotation, type):
        return ("cls", rename.get(annotation.__name__, annotation.__name__))
    return ("opaque", repr(annotation))


def _assert_classes_match(
    oracle_cls: type[BaseModel],
    package_cls: type[BaseModel],
    *,
    rename: dict[str, str],
    drop: frozenset[str],
    context: str,
    overrides: dict[str, Any] | None = None,
) -> None:
    """Field-level comparison: names, wire aliases, requiredness, annotations.

    ``overrides`` maps a field name to the verbatim package annotation pinned
    for it (the render-artifact widenings); for those fields the package is
    compared against the pin instead of the oracle's rendered annotation.
    """
    oracle_fields = oracle_cls.model_fields
    package_fields = package_cls.model_fields
    assert set(package_fields) == set(oracle_fields), f"{context}: field set differs"
    for field_name, oracle_info in oracle_fields.items():
        package_info = package_fields[field_name]
        assert package_info.alias == oracle_info.alias, f"{context}.{field_name}: wire alias differs"
        assert package_info.is_required() == oracle_info.is_required(), f"{context}.{field_name}: requiredness differs"
        widen = field_name in _WIDENED_FIELDS
        package_sig = _sig(package_info.annotation, rename={}, drop=drop, widen_dicts=widen)
        if overrides is not None and field_name in overrides:
            pinned_sig = _sig(overrides[field_name], rename={}, drop=frozenset())
            assert package_sig == pinned_sig, f"{context}.{field_name}: annotation differs from its pinned widening"
            continue
        oracle_sig = _sig(oracle_info.annotation, rename=rename, drop=frozenset(), widen_dicts=widen)
        assert package_sig == oracle_sig, f"{context}.{field_name}: annotation differs"


@pytest.mark.parametrize("version", VERSIONS)
def test_definition_sets_match(version: str) -> None:
    """Both directions: every oracle definition is in the package and vice versa."""
    oracle_defs = _module_defs(_oracle(version))
    package_defs = _module_defs(_package(version))
    rename = _synthetic_renames(_oracle(version))
    expected = {rename.get(name, name) for name in oracle_defs}
    carried = set(CARRIED_CONTENT_BLOCKS.get(version, {}))
    missing = expected - set(package_defs)
    assert not missing, f"{version}: oracle definitions missing from the package: {sorted(missing)}"
    extra = set(package_defs) - expected - carried
    assert not extra, f"{version}: package definitions with no oracle counterpart: {sorted(extra)}"


@pytest.mark.parametrize("version", VERSIONS)
def test_model_fields_match(version: str) -> None:
    """Every shared model class matches its oracle field for field."""
    oracle = _oracle(version)
    package = _package(version)
    rename = {**_synthetic_renames(oracle), **_VALUE_DOWNGRADES}
    drop = frozenset(CARRIED_CONTENT_BLOCKS.get(version, {}))
    package_classes = _module_classes(package)
    for oracle_name, oracle_cls in _module_classes(oracle).items():
        package_cls = package_classes[rename.get(oracle_name, oracle_name)]
        overrides = {
            field_name: annotation
            for (widened_version, class_name, field_name), annotation in _RENDER_ARTIFACT_WIDENED.items()
            if widened_version == version and class_name == package_cls.__name__
        }
        _assert_classes_match(
            oracle_cls,
            package_cls,
            rename=rename,
            drop=drop,
            context=f"{version}.{package_cls.__name__}",
            overrides=overrides,
        )


@pytest.mark.parametrize("version", VERSIONS)
def test_alias_definitions_match(version: str) -> None:
    """Every non-class definition (type alias) matches its oracle form."""
    oracle = _oracle(version)
    package = _package(version)
    rename = {**_synthetic_renames(oracle), **_VALUE_DOWNGRADES}
    drop = frozenset(CARRIED_CONTENT_BLOCKS.get(version, {}))
    oracle_classes = _module_classes(oracle)
    package_defs = _module_defs(package)
    for name, oracle_obj in _module_defs(oracle).items():
        if name in oracle_classes:
            continue
        package_obj = package_defs[rename.get(name, name)]
        override = _ALIAS_OVERRIDES.get((version, name))
        if override is not None:
            assert isinstance(package_obj, TypeAliasType), f"{version}.{name}: overridden alias must stay lazy"
            assert package_obj.__value__ == override, f"{version}.{name}: alias value differs from its override"
            continue
        if isinstance(oracle_obj, TypeAliasType):
            assert isinstance(package_obj, TypeAliasType), f"{version}.{name}: oracle is a lazy alias"
            oracle_sig = _sig(oracle_obj.__value__, rename=rename, drop=frozenset())
            package_sig = _sig(package_obj.__value__, rename={}, drop=drop)
        else:
            oracle_sig = _sig(oracle_obj, rename=rename, drop=frozenset())
            package_sig = _sig(package_obj, rename={}, drop=drop)
        assert package_sig == oracle_sig, f"{version}.{name}: alias value differs"


@pytest.mark.parametrize(
    ("version", "block", "introducing"),
    [
        ("v2024_11_05", "AudioContent", "v2025_03_26"),
        ("v2024_11_05", "ResourceLink", "v2025_06_18"),
        ("v2025_03_26", "ResourceLink", "v2025_06_18"),
    ],
)
def test_carried_content_block_matches_introducing_version(version: str, block: str, introducing: str) -> None:
    """A carried content block is byte-faithful to the schema that introduces it."""
    package_cls = _module_classes(_package(version))[block]
    oracle_cls = _module_classes(_oracle(introducing))[block]
    _assert_classes_match(
        oracle_cls,
        package_cls,
        rename=dict(_VALUE_DOWNGRADES),
        drop=frozenset(),
        context=f"{version}.{block} (vs {introducing} oracle)",
    )


@pytest.mark.parametrize("version", VERSIONS)
def test_extra_policy(version: str) -> None:
    """Package classes are closed except the enumerated open classes.

    Open by design: the ``_meta`` carriers (unknown ``_meta`` keys survive
    revalidation), the tool input/output schema interiors, and the
    subscription filter. Everything else is ``extra="ignore"`` so a field the
    target version never defined registers as a loss on revalidation.
    """
    classes = _module_classes(_package(version))
    expected_open: set[str] = {"SubscriptionFilter"} & set(classes)
    for cls in classes.values():
        for field_name, info in cls.model_fields.items():
            alias = info.alias or field_name
            if alias == "_meta" or alias in _OPEN_INTERIOR_ALIASES:
                expected_open.update(name for name in _model_names_in(info.annotation) if name in classes)
    for name, cls in classes.items():
        expected = "allow" if name in expected_open else "ignore"
        assert cls.model_config.get("extra") == expected, f"{version}.{name}: extra={cls.model_config.get('extra')!r}"
        assert cls.model_config.get("populate_by_name") is True, f"{version}.{name}: populate_by_name is not set"


# --- number-render closure sweep -------------------------------------------------


def _admits_int_without_float(annotation: Any, seen: frozenset[int] = frozenset()) -> bool:
    """True when ``annotation`` admits int somewhere without a float sibling.

    Walks unions, containers, Annotated metadata, and lazy aliases (cycle-safe
    via ``seen``); Literal values are exact constants, never an int admission.
    """
    if isinstance(annotation, TypeAliasType):
        if id(annotation) in seen:
            return False
        return _admits_int_without_float(annotation.__value__, seen | {id(annotation)})
    origin = get_origin(annotation)
    if origin is Annotated:
        return _admits_int_without_float(get_args(annotation)[0], seen)
    if origin is Literal:
        return False
    if origin is Union or origin is UnionType:
        members = get_args(annotation)
        if int in members and float not in members:
            return True
        return any(_admits_int_without_float(member, seen) for member in members if member is not int)
    if origin is not None:
        return any(_admits_int_without_float(arg, seen) for arg in get_args(annotation))
    return annotation is int


@pytest.mark.parametrize("version", VERSIONS)
def test_int_only_number_positions_are_classified(version: str) -> None:
    """Every package field position that admits int but not float is claimed
    by exactly one pinned table: the render-artifact widenings (the package
    must carry the float arm the schema.json rendering lost — schema.ts types
    those positions number) or the intended-integer field closure (the spec
    fact really is integral). An unclassified position fails, so a new
    integer rendering cannot land unexamined; a widened position that loses
    its float arm fails too."""
    for class_name, cls in _module_classes(_package(version)).items():
        for field_name, info in cls.model_fields.items():
            int_only = _admits_int_without_float(info.annotation)
            if (version, class_name, field_name) in _RENDER_ARTIFACT_WIDENED:
                assert not int_only, f"{version}.{class_name}.{field_name}: pinned widening lost its float arm"
            elif int_only:
                assert field_name in _INTENDED_INTEGER_FIELDS, (
                    f"{version}.{class_name}.{field_name}: int-without-float position is neither a pinned "
                    "render-artifact widening nor a pinned intended-integer field"
                )


# --- helper unit tests (synthetic data; the canonicalizers must not go vacuous) ---


def _fake_oracle(**classes: type[BaseModel]) -> ModuleType:
    module = ModuleType("fake_oracle")
    for name, cls in classes.items():
        setattr(module, name, cls)
    return module


# Alias object as test data for the canonicalizer below.
SomeAlias = TypeAliasType("SomeAlias", str)


def test_synthetic_rename_requires_a_params_or_meta_field_reference() -> None:
    # A synthetic class referenced from a field that is not `params`/`meta`
    # derives no owner-based name and keeps its generated one.
    params = create_model("Params1", __module__="fake_oracle")
    owner = create_model("Owner", __module__="fake_oracle", payload=(params | None, None))
    assert _synthetic_renames(_fake_oracle(Params1=params, Owner=owner)) == {}


def test_synthetic_rename_never_collides_with_an_existing_class_name() -> None:
    params = create_model("Params1", __module__="fake_oracle")
    owner = create_model("Owner", __module__="fake_oracle", params=(params | None, None))
    taken = create_model("OwnerParams", __module__="fake_oracle")
    assert _synthetic_renames(_fake_oracle(Params1=params, Owner=owner, OwnerParams=taken)) == {}


def test_sig_keeps_alias_references_by_name() -> None:
    assert _sig(SomeAlias, rename={}, drop=frozenset()) == ("aliasref", "SomeAlias")


def test_sig_unwraps_annotated_metadata() -> None:
    assert _sig(Annotated[str, "wire metadata"], rename={}, drop=frozenset()) == ("cls", "str")


def test_sig_collapses_a_union_left_with_one_member_after_dropping_arms() -> None:
    kept = create_model("KeptArm")
    dropped = create_model("DroppedArm")
    assert _sig(kept | dropped, rename={}, drop=frozenset({"DroppedArm"})) == ("cls", "KeptArm")


# Alias objects as test data for the int-admission walker below.
IntAlias = TypeAliasType("IntAlias", int)


def test_int_admission_walker_resolves_aliases() -> None:
    assert _admits_int_without_float(IntAlias)
    assert not _admits_int_without_float(SomeAlias)


def test_int_admission_walker_stops_on_alias_cycles() -> None:
    # A self-referential alias is walked once; revisiting it resolves False.
    assert not _admits_int_without_float(IntAlias, frozenset({id(IntAlias)}))


def test_int_admission_walker_treats_literal_values_as_constants() -> None:
    assert not _admits_int_without_float(Literal[0, 1])


def test_int_admission_walker_unwraps_annotated_metadata() -> None:
    # Annotated survives only nested inside other annotations (pydantic strips
    # it from the top level of model_fields), so the branch is pinned here.
    assert _admits_int_without_float(Annotated[int, "wire metadata"])


def test_int_admission_walker_sees_a_float_sibling() -> None:
    assert not _admits_int_without_float(int | float | None)
    assert _admits_int_without_float(dict[str, str | int | bool] | None)
