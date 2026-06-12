"""Each committed version module's effective surface equals its pinned-schema oracle.

The modules under ``src/mcp/types/v*`` hold wire-shape models in delta form: a
module defines what its protocol revision added or changed and imports the
rest from the version module that last defined it. These tests pin, per
version: the exported surface (exactly the schema's named definitions), every
definition's wire shape (recursively through the classes a field annotation
actually references, so a stale inherited reference cannot hide behind a
matching name), the import manifest's defining-module claims, the absence of
shadowed and orphan definitions, and the recorded removal set.

The oracle modules under ``tests/spec_oracles`` are regenerated verbatim from
the pinned schemas; the deliberate scaffold deltas are the annotated tolerance
tables below, and everything else must match exactly.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from types import ModuleType, UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from typing_extensions import TypeAliasType

# Protocol revisions whose version modules are committed, oldest first; later
# revisions join this list as their modules land.
MODELED_VERSIONS: tuple[str, ...] = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")

# Tolerance: value-transforming pydantic types are downgraded to plain ``str``
# in the version modules — URL normalization and base64 re-encoding would
# change wire bytes on a validate -> re-dump round trip. (``Base64Str`` needs
# no entry: it is ``Annotated[str, ...]``, so both sides compare as ``str``.)
_VALUE_DOWNGRADES = {"AnyUrl": "str", "FileUrl": "str"}

# Tolerance: the version modules widen ``structuredContent`` from
# ``dict[str, Any]`` to ``Any`` — the newest schema types the field ``Any``,
# and the wire models never narrow a value the SDK models accept.
_WIDENED_FIELDS = frozenset({"structured_content"})

# Tolerance: the pinned 2026-07-28 schema.json renders JSONValue's primitive
# branch as ["string", "integer", "boolean"], but its schema.ts source defines
# all six JSON types (string | number | boolean | null | object | array). The
# oracle reproduces the render verbatim; the version module follows the
# schema.ts definition so fractional numbers and nulls validate. The module
# alias is pinned here verbatim, so any further drift still fails.
_ALIAS_OVERRIDES: dict[tuple[str, str], str] = {
    ("v2026_07_28", "JSONValue"): "JSONObject | list[JSONValue] | str | int | float | bool | None",
}

# Tolerance: the pinned schema.json renderings type a few more schema.ts
# `number` positions as "integer" — the same render artifact fixed for the
# JSONValue alias. The version modules keep the int arm and gain a float arm
# at exactly these positions, so fractional elicitation answers and
# number-schema bounds have a wire form; the oracles keep the render
# verbatim, and the module annotation is pinned here verbatim so any further
# drift still fails. (Defining module, class, field) -> the exact module
# annotation.
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

# The closure for every OTHER module field that admits int but not float:
# the integer rendering is the intended type, justified per field name by the
# spec fact in plain words. A field absent here whose annotation is
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

# Tolerance: content blocks carried into modules older than the schema that
# introduces them, so emitting such a block to an older peer passes it through
# instead of refusing. Maps module -> {class name -> introducing oracle}; the
# carried class is pinned against that oracle in
# test_carried_content_blocks_match_the_introducing_version, and dropped from
# union comparisons against this version's own oracle.
CARRIED_CONTENT_BLOCKS: dict[str, dict[str, str]] = {
    "v2024_11_05": {"AudioContent": "v2025_03_26", "ResourceLink": "v2025_06_18"},
    "v2025_03_26": {"ResourceLink": "v2025_06_18"},
}

# The 2024-11-05 schema names a definition ``Annotated``, which would shadow
# ``typing.Annotated`` in a Python module; the generator resolves the
# collision by appending ``Model``, on the oracle and version-module sides
# alike. The schema's named surface maps through this table everywhere.
_COLLISION_RENAMES = {"Annotated": "AnnotatedModel"}

# Tool input/output schema interiors stay ``extra="allow"``: at every revision
# these declare only a subset of JSON Schema keywords and the rest must ride
# extra fields through revalidation.
_OPEN_INTERIOR_ALIASES = frozenset({"inputSchema", "outputSchema"})

Sig = tuple[Any, ...]


def _module_name(version: str) -> str:
    return "v" + version.replace("-", "_")


def _package(version: str) -> ModuleType:
    return importlib.import_module(f"mcp.types.{_module_name(version)}")


def _oracle(version: str) -> ModuleType:
    return importlib.import_module(f"tests.spec_oracles.{_module_name(version)}")


def _surface(version: str) -> set[str]:
    """The schema's named definitions for a version, as module attribute names."""
    spec_defs: tuple[str, ...] = _oracle(version).SPEC_DEFS
    return {_COLLISION_RENAMES.get(name, name) for name in spec_defs}


def _local_classes(mod: ModuleType) -> dict[str, type[BaseModel]]:
    """Model classes a module itself defines (inherited names excluded)."""
    return {
        name: obj
        for name, obj in vars(mod).items()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == mod.__name__
    }


def _alias_value(obj: Any) -> Any:
    """A lazy alias's value, or the object itself for eager aliases."""
    return obj.__value__ if isinstance(obj, TypeAliasType) else obj


def _models_in(annotation: Any) -> dict[str, type[BaseModel]]:
    """Model classes appearing anywhere in an annotation, keyed by class name."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation.__name__: annotation}
    found: dict[str, type[BaseModel]] = {}
    for arg in get_args(annotation):
        found.update(_models_in(arg))
    return found


def _synthetic_renames(oracle: ModuleType) -> dict[str, str]:
    """Oracle synthetic class name -> version-module class name.

    Mirrors the generator's deterministic-naming pass: a synthesized
    ``Params<n>``/``Meta<n>`` class referenced by exactly one field of one
    owner is named ``<Owner>Params``/``<Owner>Meta``; shared synthetics keep
    their generated names.
    """
    classes = _local_classes(oracle)
    synthetic = {name for name in classes if re.fullmatch(r"(?:Params|Meta)\d*", name)}
    references: dict[str, list[tuple[str, str]]] = {name: [] for name in synthetic}
    for owner_name, cls in classes.items():
        for field_name, info in cls.model_fields.items():
            for name in synthetic & set(_models_in(info.annotation)):
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
    member sets. ``drop`` removes the carried content-block arms from
    version-module unions; ``widen_dicts`` collapses ``dict[str, Any]`` to
    ``Any`` for the widened-field tolerance.
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


def _assert_models_match(
    oracle_cls: type[BaseModel],
    package_cls: type[BaseModel],
    *,
    rename: dict[str, str],
    drop: frozenset[str],
    context: str,
    seen: set[tuple[int, int]],
    recurse: bool = True,
    overrides: dict[tuple[str, str], Any] | None = None,
) -> None:
    """Field-level comparison, recursing into the classes annotations reference.

    Recursion follows the annotation's actual class objects — not the module
    namespace — so an inherited definition whose reference closure went stale
    fails here even when every name still resolves. The synthesized helper
    classes (anonymous nested schema objects) are compared exactly this way:
    they are reachable only through the named definitions that reference them.

    ``overrides`` maps (class name, field name) to the verbatim module
    annotation pinned for it (the render-artifact widenings); those fields are
    compared against the pin instead of the oracle's rendered annotation.
    """
    pair = (id(oracle_cls), id(package_cls))
    if pair in seen:
        return
    seen.add(pair)
    oracle_fields = oracle_cls.model_fields
    package_fields = package_cls.model_fields
    assert set(package_fields) == set(oracle_fields), f"{context}: field set differs"
    for field_name, oracle_info in oracle_fields.items():
        package_info = package_fields[field_name]
        assert package_info.alias == oracle_info.alias, f"{context}.{field_name}: wire alias differs"
        assert package_info.is_required() == oracle_info.is_required(), f"{context}.{field_name}: requiredness differs"
        if not oracle_info.is_required() and oracle_info.default is not PydanticUndefined:
            assert package_info.default == oracle_info.default, f"{context}.{field_name}: default differs"
        widen = field_name in _WIDENED_FIELDS
        package_sig = _sig(package_info.annotation, rename={}, drop=drop, widen_dicts=widen)
        if overrides is not None and (package_cls.__name__, field_name) in overrides:
            pinned_sig = _sig(overrides[package_cls.__name__, field_name], rename={}, drop=frozenset())
            assert package_sig == pinned_sig, f"{context}.{field_name}: annotation differs from its pinned widening"
            continue
        oracle_sig = _sig(oracle_info.annotation, rename=rename, drop=frozenset(), widen_dicts=widen)
        assert package_sig == oracle_sig, f"{context}.{field_name}: annotation differs"
        if not recurse:
            continue
        package_models = _models_in(package_info.annotation)
        for oracle_ref_name, oracle_ref in _models_in(oracle_info.annotation).items():
            target = rename.get(oracle_ref_name, oracle_ref_name)
            package_ref = package_models.get(target)
            assert package_ref is not None, f"{context}.{field_name}: no referenced class {target}"
            _assert_models_match(
                oracle_ref,
                package_ref,
                rename=rename,
                drop=drop,
                context=f"{context}.{field_name}->{target}",
                seen=seen,
                overrides=overrides,
            )


def _versions_by_module(module: str) -> str:
    return module.removeprefix("v").replace("_", "-")


def _manifest_imports(version: str) -> dict[str, list[str]]:
    """Defining-module -> imported names, parsed from the module source."""
    tree = ast.parse(Path(_package(version).__file__ or "").read_text())
    manifest: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("mcp.types.v"):
            module = (node.module or "").removeprefix("mcp.types.")
            manifest.setdefault(module, []).extend(alias.name for alias in node.names)
    return manifest


def _top_level_definitions(version: str) -> set[str]:
    """Names a version module defines at top level (imports excluded)."""
    tree = ast.parse(Path(_package(version).__file__ or "").read_text())
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            names.add(node.targets[0].id)
    return names - {"__all__", "REMOVED_FROM_PREVIOUS_VERSION"}


def _referenced_names(version: str) -> dict[str, set[str]]:
    """Per top-level definition, the sibling names its body mentions.

    String annotations count: with lazy annotation evaluation every reference
    can hide inside a string, so each string constant that parses as an
    expression contributes its names.
    """
    tree = ast.parse(Path(_package(version).__file__ or "").read_text())
    local = _top_level_definitions(version)
    refs: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            name = node.name
        elif isinstance(node, ast.AnnAssign | ast.Assign):
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            if not isinstance(target, ast.Name) or target.id in {"__all__", "REMOVED_FROM_PREVIOUS_VERSION"}:
                continue
            name = target.id
        else:
            continue
        found: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in local:
                found.add(sub.id)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                try:
                    expr = ast.parse(sub.value, mode="eval")
                except SyntaxError:
                    continue
                found.update(n.id for n in ast.walk(expr) if isinstance(n, ast.Name) and n.id in local)
        refs[name] = found - {name}
    return refs


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_module_surface_equals_the_pinned_schema_surface(version: str) -> None:
    """``__all__`` is exactly the schema's named definitions, both directions."""
    package = _package(version)
    exported = set(package.__all__)
    assert len(package.__all__) == len(exported), f"{version}: duplicate names in __all__"
    assert exported == _surface(version)
    for name in exported:
        assert getattr(package, name, None) is not None, f"{version}: {name} listed but not resolvable"


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_every_definition_matches_its_oracle_shape(version: str) -> None:
    """Every named definition matches its oracle, recursively through helpers.

    The version-module counterpart is resolved through the module's effective
    namespace, then compared recursively through the actual annotation
    referents, so both a missing redefinition and a stale inherited closure
    fail. The synthesized helper classes are covered by the recursion: each is
    reachable from the named definitions that reference it, and an inherited
    name is compared as the object the inherited annotation really points at.
    """
    oracle = _oracle(version)
    package = _package(version)
    rename = {**_synthetic_renames(oracle), **_COLLISION_RENAMES, **_VALUE_DOWNGRADES}
    drop = frozenset(CARRIED_CONTENT_BLOCKS.get(_module_name(version), {}))
    overrides = {
        (class_name, field_name): annotation
        for (module, class_name, field_name), annotation in _RENDER_ARTIFACT_WIDENED.items()
        if module == _module_name(version)
    }
    seen: set[tuple[int, int]] = set()
    for target in sorted(_surface(version)):
        oracle_obj = getattr(oracle, target)
        package_obj = getattr(package, target, None)
        assert package_obj is not None, f"{version}: oracle definition {target} missing"
        context = f"{version}.{target}"
        if isinstance(oracle_obj, type) and issubclass(oracle_obj, BaseModel):
            assert isinstance(package_obj, type) and issubclass(package_obj, BaseModel), f"{context}: not a model"
            _assert_models_match(
                oracle_obj, package_obj, rename=rename, drop=drop, context=context, seen=seen, overrides=overrides
            )
            continue
        override = _ALIAS_OVERRIDES.get((_module_name(version), target))
        if override is not None:
            assert _alias_value(package_obj) == override, f"{context}: widened alias drifted"
            continue
        oracle_value = _alias_value(oracle_obj)
        package_value = _alias_value(package_obj)
        oracle_sig = _sig(oracle_value, rename=rename, drop=frozenset())
        package_sig = _sig(package_value, rename={}, drop=drop)
        assert package_sig == oracle_sig, f"{context}: alias value differs"
        package_models = _models_in(package_value)
        for ref_name, oracle_ref in _models_in(oracle_value).items():
            ref_target = rename.get(ref_name, ref_name)
            package_ref = package_models.get(ref_target)
            assert package_ref is not None, f"{context}: no referenced class {ref_target}"
            _assert_models_match(
                oracle_ref,
                package_ref,
                rename=rename,
                drop=drop,
                context=f"{context}->{ref_target}",
                seen=seen,
                overrides=overrides,
            )


@pytest.mark.parametrize(
    ("version", "block", "introducing"),
    [
        ("2024-11-05", "AudioContent", "2025-03-26"),
        ("2024-11-05", "ResourceLink", "2025-06-18"),
        ("2025-03-26", "ResourceLink", "2025-06-18"),
    ],
)
def test_carried_content_blocks_match_the_introducing_version(version: str, block: str, introducing: str) -> None:
    """A carried content block is shape-faithful to the schema that introduces it.

    Shallow on purpose: the carried definition keeps its own revision's
    reference closure (its ``Annotations`` is this version's, not the
    introducing version's), so referenced classes compare by name only here
    and recursively in the per-version oracle comparison.
    """
    package_cls = _local_classes(_package(version))[block]
    oracle_cls = _local_classes(_oracle(introducing))[block]
    _assert_models_match(
        oracle_cls,
        package_cls,
        rename=dict(_VALUE_DOWNGRADES),
        drop=frozenset(),
        context=f"{version}.{block} (vs the {introducing} oracle)",
        seen=set(),
        recurse=False,
    )


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_extra_policy_is_closed_except_the_enumerated_open_classes(version: str) -> None:
    """Locally defined classes are closed except the enumerated open classes.

    Open by design: the ``_meta`` carriers (unknown ``_meta`` keys must
    survive revalidation), the tool input/output schema interiors, and the
    subscription filter. Everything else is ``extra="ignore"`` so a field the
    target revision never defined registers as a loss on revalidation.
    """
    package = _package(version)
    classes = _local_classes(package)
    expected_open: set[str] = {"SubscriptionFilter"} & set(classes)
    for cls in classes.values():
        for field_name, info in cls.model_fields.items():
            alias = info.alias or field_name
            if alias == "_meta" or alias in _OPEN_INTERIOR_ALIASES:
                expected_open.update(name for name in _models_in(info.annotation) if name in classes)
    for name, cls in classes.items():
        expected = "allow" if name in expected_open else "ignore"
        assert cls.model_config.get("extra") == expected, f"{version}.{name}: extra={cls.model_config.get('extra')!r}"
        assert cls.model_config.get("populate_by_name") is True, f"{version}.{name}: populate_by_name is not set"


def _namespace_classes(mod: ModuleType) -> dict[str, type[BaseModel]]:
    """Every model class in a module's effective namespace, inherited or local."""
    return {name: obj for name, obj in vars(mod).items() if isinstance(obj, type) and issubclass(obj, BaseModel)}


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


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_int_only_number_positions_are_classified(version: str) -> None:
    """Every module field position that admits int but not float is claimed
    by exactly one pinned table: the render-artifact widenings (the module
    must carry the float arm the schema.json rendering lost — schema.ts types
    those positions number) or the intended-integer field closure (the spec
    fact really is integral). An unclassified position fails, so a new
    integer rendering cannot land unexamined; a widened position that loses
    its float arm fails too. Positions key on the class's defining module —
    in the delta layout an inherited class is the defining module's object."""
    for cls in _namespace_classes(_package(version)).values():
        home = cls.__module__.removeprefix("mcp.types.")
        for field_name, info in cls.model_fields.items():
            int_only = _admits_int_without_float(info.annotation)
            if (home, cls.__name__, field_name) in _RENDER_ARTIFACT_WIDENED:
                assert not int_only, f"{version}.{cls.__name__}.{field_name}: pinned widening lost its float arm"
            elif int_only:
                assert field_name in _INTENDED_INTEGER_FIELDS, (
                    f"{version}.{cls.__name__}.{field_name}: int-without-float position is neither a pinned "
                    "render-artifact widening nor a pinned intended-integer field"
                )


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_manifest_imports_name_the_defining_module(version: str) -> None:
    """Every import line names the module that really last defined the name.

    For classes the defining module is recorded on the object; for aliases the
    named module's source must contain the defining assignment. In both cases
    no module strictly between the named definer and this one may redefine the
    name — an import from a too-old module is wrong even when the shapes
    happen to coincide.
    """
    package = _package(version)
    modeled_modules = [_module_name(v) for v in MODELED_VERSIONS]
    for definer, names in _manifest_imports(version).items():
        assert definer in modeled_modules, f"{version}: manifest imports from uncommitted module {definer}"
        definer_definitions = _top_level_definitions(_versions_by_module(definer))
        between = modeled_modules[modeled_modules.index(definer) + 1 : modeled_modules.index(_module_name(version))]
        for name in names:
            obj = getattr(package, name)
            if isinstance(obj, type) and issubclass(obj, BaseModel):
                assert obj.__module__ == f"mcp.types.{definer}", f"{version}.{name}: defined in {obj.__module__}"
            else:
                assert name in definer_definitions, f"{version}.{name}: {definer} does not define it"
            redefiners = [m for m in between if name in _top_level_definitions(_versions_by_module(m))]
            assert not redefiners, f"{version}.{name}: redefined after {definer} in {redefiners}"


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_names_are_exactly_one_of_imported_or_defined(version: str) -> None:
    """No silent shadowing: a name is either imported in the manifest or defined below, never both."""
    defined = _top_level_definitions(version)
    imported = {name for names in _manifest_imports(version).values() for name in names}
    shadowed = defined & imported
    assert not shadowed, f"{version}: defined names shadow manifest imports: {sorted(shadowed)}"
    for name in _package(version).__all__:
        assert name in defined or name in imported, f"{version}.{name}: neither imported nor defined"


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_no_orphan_definitions(version: str) -> None:
    """Every local definition outside ``__all__`` earns its place.

    A non-exported definition must be a helper reachable from an exported
    definition of this module, or a carried content block (defined in modules
    older than the schema that introduces it so emission passes the block
    through un-gated).
    """
    package = _package(version)
    defined = _top_level_definitions(version)
    exported = set(package.__all__)
    carried = set(CARRIED_CONTENT_BLOCKS.get(_module_name(version), {}))
    refs = _referenced_names(version)
    reachable: set[str] = set()
    frontier = list(defined & exported)
    while frontier:
        name = frontier.pop()
        for ref in refs.get(name, set()):
            if ref in defined and ref not in reachable:
                reachable.add(ref)
                frontier.append(ref)
    orphans = defined - exported - carried - reachable
    assert not orphans, f"{version}: definitions nothing exports or references: {sorted(orphans)}"


# A lazy alias like the oracles use for recursive definitions; only the name
# rides into its signature.
_LazyAlias = TypeAliasType("_LazyAlias", int)

# Alias objects as test data for the int-admission walker.
_StrAlias = TypeAliasType("_StrAlias", str)


def test_int_admission_walker_resolves_aliases() -> None:
    assert _admits_int_without_float(_LazyAlias)
    assert not _admits_int_without_float(_StrAlias)


def test_int_admission_walker_stops_on_alias_cycles() -> None:
    # A self-referential alias is walked once; revisiting it resolves False.
    assert not _admits_int_without_float(_LazyAlias, frozenset({id(_LazyAlias)}))


def test_int_admission_walker_treats_literal_values_as_constants() -> None:
    assert not _admits_int_without_float(Literal[0, 1])


def test_int_admission_walker_unwraps_annotated_metadata() -> None:
    # pydantic strips Annotated from model_fields annotations, but raw
    # annotations passed to the walker may still carry it.
    assert _admits_int_without_float(Annotated[int, "wire-metadata"])
    assert not _admits_int_without_float(Annotated[float, "wire-metadata"])


def test_int_admission_walker_sees_a_float_sibling() -> None:
    assert not _admits_int_without_float(int | float | None)
    assert _admits_int_without_float(dict[str, str | int | bool] | None)


def test_annotation_signatures_cover_forms_later_revisions_add() -> None:
    """The signature canonicalizer handles annotation forms the two oldest revisions never produce.

    Later schema revisions add lazy (recursive) aliases, the widened
    ``structuredContent`` dict, and carried arms whose removal collapses a
    union to one member; nested ``Annotated`` metadata and non-type metadata
    objects can appear anywhere. Pinning these here keeps the comparison
    machinery trustworthy before the modules that need it land.
    """
    assert _sig(_LazyAlias, rename={}, drop=frozenset()) == ("aliasref", "_LazyAlias")
    assert _sig(Annotated[int, "wire-metadata"], rename={}, drop=frozenset()) == ("cls", "int")

    class Carried(BaseModel):
        pass

    assert _sig(str | Carried, rename={}, drop=frozenset({"Carried"})) == ("cls", "str")
    assert _sig(dict[str, Any], rename={}, drop=frozenset(), widen_dicts=True) == ("any",)
    assert _sig(dict[str, Any], rename={}, drop=frozenset()) == ("dict", ("cls", "str"), ("any",))
    assert _sig(123, rename={}, drop=frozenset()) == ("opaque", "123")


def test_synthetic_rename_derivation_skips_unnameable_helpers() -> None:
    """A synthetic helper keeps its generated name when no derived name fits.

    The derivation only renames a helper referenced by exactly one ``params``
    or ``meta`` field whose derived ``<Owner>Params``/``<Owner>Meta`` name is
    free; a helper hanging off another field, or whose derived name is taken,
    keeps its generated name on both sides of the comparison.
    """
    fake = ModuleType("fake_oracle")

    class Params1(BaseModel):
        pass

    class Params2(BaseModel):
        pass

    class Owner(BaseModel):
        result: Params1 | None = None
        params: Params2 | None = None

    class OwnerParams(BaseModel):
        pass

    for cls in (Params1, Params2, Owner, OwnerParams):
        cls.__module__ = "fake_oracle"
        setattr(fake, cls.__name__, cls)
    assert _synthetic_renames(fake) == {}


@pytest.mark.parametrize("version", MODELED_VERSIONS)
def test_removed_names_match_the_oracle_diff(version: str) -> None:
    """The removal record equals the oracle surface diff against the predecessor."""
    package = _package(version)
    index = MODELED_VERSIONS.index(version)
    if index == 0:
        assert not hasattr(package, "REMOVED_FROM_PREVIOUS_VERSION")
        return
    removed = package.REMOVED_FROM_PREVIOUS_VERSION
    assert isinstance(removed, frozenset)
    assert removed == _surface(MODELED_VERSIONS[index - 1]) - _surface(version)
