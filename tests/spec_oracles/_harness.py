"""Comparison library for the spec-oracle burn-down harness.

Compares the generated, SHA-pinned oracle modules in this directory against the
SDK's hand-curated types (`mcp.types`, with `mcp.types.jsonrpc` as a secondary
search module). Every divergence becomes a `Finding`; hard findings fail the
gate in `test_burndown.py` unless they are allowlisted in
`burndown_allowlist.json`, and allowlisted entries that no longer fire are
*stale* and also fail the gate (the two-way ratchet that makes the allowlist a
burn-down list rather than a suppression file).

Finding ids are stable strings: ``<oracle>/<name>[.<wire-field>]#<CHECK>``.
Aggregated findings (checks that run once across all oracles) use the
pseudo-oracle ``sdk``.

Checks:

Hard (fail unless allowlisted):
- SPEC-TYPE-MISSING: oracle def has no SDK counterpart.
- SPEC-FIELD-MISSING: oracle model field's wire name absent on the SDK model.
- SDK-REQUIRED-NOT-IN-SPEC: SDK requires a wire field this version's oracle
  does not require (optional or absent) - the inbound-leniency invariant.
- TYPE-NARROWER: SDK annotation provably rejects values the oracle accepts.
- SDK-TYPE-PHANTOM (aggregated): SDK public type maps to no def in any oracle
  and is not machinery.
- SDK-FIELD-PHANTOM (aggregated): SDK model field's wire name appears in no
  version's oracle for the paired def.

Soft (reported, never fail):
- SPEC-FIELD-OPTIONAL-IN-SDK: oracle requires, SDK optional (expected superset
  behavior).
- TYPE-WIDER: SDK widens (adds `| None`, `Any`, superset Literal, ...).
- TYPE-INCOMPARABLE: the type algebra cannot relate the two annotations.

Allowlist pseudo-checks (never emitted as findings; validated by
`schema_gap_applies` instead so the ratchet still covers them):
- VACUOUS-SCHEMA: the ext-tasks schema lost a core `$ref` (vacuous `anyOf`),
  so the oracle faithfully says `Any` there.
- REQUIRED-UNVERIFIABLE: the ext-tasks schema lost the `required` array on a
  Result-intersection def, so the oracle has every field optional.

Allowlist categories (each entry's `reason` must stand on its own — it is
the only record a reader gets):
- not-yet-implemented: planned SDK work; the entry burns down when it lands.
- deliberate-deviation: a reviewed divergence the SDK keeps on purpose.
- schema-gap: the pinned schema itself is defective at this site (see the
  pseudo-checks above).
- suspected-sdk-bug: the SDK side looks wrong; the reason must describe the
  suspected defect and what would resolve it.
"""

from __future__ import annotations

import importlib
import json
import types
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import AnyUrl, Base64Str, BaseModel, FileUrl
from pydantic.fields import FieldInfo
from typing_extensions import TypeAliasType, is_typeddict

import mcp.types
import mcp.types.jsonrpc
from mcp.types._spec_names import SDK_TO_SCHEMA_RENAMES

ORACLE_PACKAGE = "tests.spec_oracles"
ORACLE_MODULES: tuple[str, ...] = (
    "v2024_11_05",
    "v2025_03_26",
    "v2025_06_18",
    "v2025_11_25",
    "v2026_07_28",
    "ext_tasks",
)

SDK_MODULES: tuple[ModuleType, ...] = (mcp.types, mcp.types.jsonrpc)

ALLOWLIST_PATH = Path(__file__).parent / "burndown_allowlist.json"

HARD_CHECKS = frozenset(
    {
        "SPEC-TYPE-MISSING",
        "SPEC-FIELD-MISSING",
        "SDK-REQUIRED-NOT-IN-SPEC",
        "TYPE-NARROWER",
        "SDK-TYPE-PHANTOM",
        "SDK-FIELD-PHANTOM",
    }
)
SOFT_CHECKS = frozenset({"SPEC-FIELD-OPTIONAL-IN-SDK", "TYPE-WIDER", "TYPE-INCOMPARABLE"})
GAP_CHECKS = frozenset({"VACUOUS-SCHEMA", "REQUIRED-UNVERIFIABLE"})
CATEGORIES = frozenset({"not-yet-implemented", "deliberate-deviation", "schema-gap", "suspected-sdk-bug"})

# Spec def name -> SDK attribute name: the inverse of the SDK's reviewed
# rename record (each entry's rationale is commented there). Applies to every
# oracle; NAME_MAP_BY_ORACLE overrides per oracle module.
NAME_MAP: dict[str, str] = {schema: sdk for sdk, schema in SDK_TO_SCHEMA_RENAMES.items()}
NAME_MAP_BY_ORACLE: dict[str, dict[str, str]] = {
    # The 2025-06-18 schema renamed ResourceReference to ResourceTemplateReference;
    # the SDK uses the new name for all versions. Version-scoped pairing like
    # this stays here: SDK_TO_SCHEMA_RENAMES is one flat SDK name -> schema
    # name map and cannot say "renamed at version X".
    "v2024_11_05": {"ResourceReference": "ResourceTemplateReference"},
    "v2025_03_26": {"ResourceReference": "ResourceTemplateReference"},
}

# SDK public names exempt from SDK-TYPE-PHANTOM: machinery that has no spec
# def on purpose. Anything less obvious belongs in the allowlist instead,
# where it stays visible in the burn-down report.
SDK_MACHINERY: frozenset[str] = frozenset(
    {
        # Protocol version constants (schema.ts constants, not $defs).
        "LATEST_PROTOCOL_VERSION",
        "DEFAULT_NEGOTIATED_VERSION",
        # JSON-RPC / MCP error-code int constants.
        "CONNECTION_CLOSED",
        "REQUEST_TIMEOUT",
        "REQUEST_CANCELLED",
        "PARSE_ERROR",
        "INVALID_REQUEST",
        "METHOD_NOT_FOUND",
        "INVALID_PARAMS",
        "INTERNAL_ERROR",
        "URL_ELICITATION_REQUIRED",
        # Module-level TypeAdapter instances.
        "client_request_adapter",
        "client_notification_adapter",
        "client_result_adapter",
        "server_request_adapter",
        "server_notification_adapter",
        "server_result_adapter",
        "jsonrpc_message_adapter",
        # TypedDict plumbing for request _meta (paired with RequestMetaObject
        # via NAME_MAP; the TypedDict itself is not a def).
        "RequestParamsMeta",
        # Capability sub-models lifted from inline (non-$defs) schema objects.
        "PromptsCapability",
        "ResourcesCapability",
        "RootsCapability",
        "ToolsCapability",
        "LoggingCapability",
        "CompletionsCapability",
        "SamplingCapability",
        "SamplingContextCapability",
        "SamplingToolsCapability",
        "ElicitationCapability",
        "FormElicitationCapability",
        "UrlElicitationCapability",
        # Models/aliases lifted from inline (non-$defs) schema objects.
        "Completion",  # CompleteResult.completion inline object
        "CompletionArgument",  # CompleteRequest.params.argument inline object
        "CompletionContext",  # CompleteRequest.params.context inline object
        "ElicitCompleteNotificationParams",  # inline params at the pinned SHA
        "IconTheme",  # Icon.theme inline enum
        "IncludeContext",  # CreateMessageRequest.params.includeContext inline enum
        "StopReason",  # CreateMessageResult.stopReason inline string union
    }
)

Sig = tuple[Any, ...]

_ANY: Sig = ("any",)
_NULL: Sig = ("null",)


@dataclass(frozen=True)
class Finding:
    """One divergence between an oracle def and the SDK's curated types."""

    check: str
    oracle: str
    name: str
    field: str | None
    detail: str

    @property
    def hard(self) -> bool:
        return self.check in HARD_CHECKS

    @property
    def id(self) -> str:
        field_part = f".{self.field}" if self.field is not None else ""
        return f"{self.oracle}/{self.name}{field_part}#{self.check}"


@dataclass(frozen=True)
class AllowlistEntry:
    """One allowlisted finding (or schema-gap exemption)."""

    id: str
    check: str
    oracle: str
    name: str
    field: str | None
    category: str
    reason: str
    track: str | None


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[AllowlistEntry]:
    """Load and validate the burn-down allowlist."""
    with path.open() as f:
        raw: dict[str, Any] = json.load(f)
    entries: list[AllowlistEntry] = []
    for item in raw["entries"]:
        entry = AllowlistEntry(
            id=item["id"],
            check=item["check"],
            oracle=item["oracle"],
            name=item["name"],
            field=item.get("field"),
            category=item["category"],
            reason=item["reason"],
            track=item.get("track"),
        )
        field_part = f".{entry.field}" if entry.field is not None else ""
        expected_id = f"{entry.oracle}/{entry.name}{field_part}#{entry.check}"
        if entry.id != expected_id:
            raise ValueError(f"allowlist entry id {entry.id!r} does not match its parts ({expected_id!r})")
        if entry.category not in CATEGORIES:
            raise ValueError(f"allowlist entry {entry.id!r}: unknown category {entry.category!r}")
        if entry.check not in HARD_CHECKS | GAP_CHECKS:
            raise ValueError(f"allowlist entry {entry.id!r}: only hard findings can be allowlisted")
        if entry.check in GAP_CHECKS and entry.category != "schema-gap":
            raise ValueError(f"allowlist entry {entry.id!r}: {entry.check} entries must be category schema-gap")
        if entry.category == "schema-gap" and entry.check not in GAP_CHECKS:
            raise ValueError(f"allowlist entry {entry.id!r}: schema-gap entries must use a gap pseudo-check")
        entries.append(entry)
    ids = [e.id for e in entries]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate allowlist ids: {dupes}")
    return entries


def oracle_module(name: str) -> ModuleType:
    """Import an oracle module lazily (keeps collection-time imports cheap)."""
    return importlib.import_module(f"{ORACLE_PACKAGE}.{name}")


def resolve_sdk_name(oracle: str, def_name: str) -> str:
    """Spec def name -> expected SDK attribute name."""
    by_oracle = NAME_MAP_BY_ORACLE.get(oracle, {})
    return by_oracle.get(def_name, NAME_MAP.get(def_name, def_name))


def sdk_lookup(name: str) -> Any:
    """Find an SDK counterpart by name, searching SDK_MODULES in order."""
    for module in SDK_MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    return None


_REVERSE_NAME_MAP: dict[str, str] = {sdk: spec for spec, sdk in NAME_MAP.items()}


def _normalize_model_name(name: str, *, sdk: bool) -> str:
    """Map SDK model names back to spec names so paired models compare equal."""
    return _REVERSE_NAME_MAP.get(name, name) if sdk else name


def wire_fields(model: type[BaseModel]) -> dict[str, FieldInfo]:
    """Map wire name (serialization alias chain) -> FieldInfo for a model."""
    fields: dict[str, FieldInfo] = {}
    for field_name, info in model.model_fields.items():
        alias = info.serialization_alias or info.alias
        fields[alias or field_name] = info
    return fields


def sig(annotation: Any, *, sdk: bool, _seen: frozenset[str] = frozenset()) -> Sig:
    """Canonicalize an annotation into a comparable signature tuple."""
    if annotation is None or annotation is type(None):
        return _NULL
    if annotation is Any:
        return _ANY
    if annotation == Base64Str:
        return ("base64",)
    if isinstance(annotation, TypeAliasType):
        name = annotation.__name__
        if name in _seen:
            return ("recursive", name)
        return sig(annotation.__value__, sdk=sdk, _seen=_seen | {name})
    origin = get_origin(annotation)
    if origin is not None and str(origin) == "typing.Annotated":
        return sig(get_args(annotation)[0], sdk=sdk, _seen=_seen)
    if origin is Literal:
        return ("lit", frozenset(get_args(annotation)))
    if origin is Union or origin is types.UnionType:
        members = frozenset(sig(arg, sdk=sdk, _seen=_seen) for arg in get_args(annotation))
        if len(members) == 1:
            return next(iter(members))
        return ("union", members)
    if origin in (list, tuple, set, frozenset):
        args = get_args(annotation)
        item = sig(args[0], sdk=sdk, _seen=_seen) if args else _ANY
        return ("list", item)
    if origin is dict:
        args = get_args(annotation)
        if args:
            return ("dict", sig(args[0], sdk=sdk, _seen=_seen), sig(args[1], sdk=sdk, _seen=_seen))
        return ("dict", _ANY, _ANY)
    if is_typeddict(annotation):
        # Open dict semantics: constraints on individual TypedDict keys are out
        # of scope for the v1 algebra.
        return ("dict", ("prim", "str"), _ANY)
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return ("model", _normalize_model_name(annotation.__name__, sdk=sdk))
        if issubclass(annotation, FileUrl):
            return ("url", "file")
        if issubclass(annotation, AnyUrl):
            return ("url", "any")
        if annotation is bool:
            return ("prim", "bool")
        if annotation is int:
            return ("prim", "int")
        if annotation is float:
            return ("prim", "float")
        if annotation is str:
            return ("prim", "str")
        return ("opaque", f"{annotation.__module__}.{annotation.__qualname__}")
    return ("opaque", repr(annotation))


Compat = Literal["equal", "sdk_wider", "sdk_narrower", "incomparable"]


def _members(s: Sig) -> frozenset[Sig]:
    if s[0] == "union":
        members: frozenset[Sig] = s[1]
        return members
    return frozenset({s})


def _strip_optional_null(s: Sig) -> Sig:
    """Drop the `| None` optionality artifact from an optional field's signature.

    Both the generator and the SDK encode "field may be absent" as
    ``X | None = <default>``; the null member says nothing about wire
    nullability there, so comparing optional fields with it inflates noise.
    Required fields keep their null members (genuine wire nullability, e.g.
    JSONRPCError.id).
    """
    if s[0] != "union":
        return s
    members = frozenset(m for m in _members(s) if m != _NULL)
    if not members:
        return _NULL
    if len(members) == 1:
        return next(iter(members))
    return ("union", members)


def _lit_base(values: frozenset[Any]) -> str | None:
    """The primitive name shared by all values of a Literal, if any."""
    bases = {type(v).__name__ for v in values}
    return next(iter(bases)) if len(bases) == 1 else None


def compat(spec: Sig, sdk: Sig) -> Compat:
    """Relate a spec-side signature to an SDK-side signature.

    `sdk_wider` means the SDK accepts everything the spec accepts (and more);
    `sdk_narrower` means the SDK provably rejects spec-valid values. Only
    `sdk_narrower` becomes a hard finding.
    """
    if spec == sdk:
        return "equal"
    if sdk == _ANY:
        return "sdk_wider"
    if spec == _ANY:
        return "sdk_narrower"
    spec_members = _members(spec)
    sdk_members = _members(sdk)
    if len(spec_members) > 1 or len(sdk_members) > 1:
        saw_incomparable = False
        all_accepted = True
        for spec_member in spec_members:
            results = [compat(spec_member, sdk_member) for sdk_member in sdk_members]
            if any(r in ("equal", "sdk_wider") for r in results):
                continue
            all_accepted = False
            if any(r == "incomparable" for r in results):
                saw_incomparable = True
        if all_accepted:
            return "sdk_wider"
        return "incomparable" if saw_incomparable else "sdk_narrower"
    return _compat_single(spec, sdk)


def _compat_single(spec: Sig, sdk: Sig) -> Compat:
    """compat() for two non-union signatures that are not equal and not Any."""
    spec_kind, sdk_kind = spec[0], sdk[0]
    if spec_kind == "lit" and sdk_kind == "lit":
        spec_values: frozenset[Any] = spec[1]
        sdk_values: frozenset[Any] = sdk[1]
        if spec_values <= sdk_values:
            return "sdk_wider"
        if sdk_values < spec_values:
            return "sdk_narrower"
        return "incomparable"
    if spec_kind == "lit" and sdk_kind == "prim":
        return "sdk_wider" if _lit_base(spec[1]) == sdk[1] else "incomparable"
    if spec_kind == "prim" and sdk_kind == "lit":
        return "sdk_narrower" if _lit_base(sdk[1]) == spec[1] else "incomparable"
    if spec_kind == "prim" and sdk_kind == "prim":
        if spec[1] == "int" and sdk[1] == "float":
            return "sdk_wider"
        if spec[1] == "float" and sdk[1] == "int":
            return "sdk_narrower"
        return "incomparable"
    if spec_kind == "base64":
        if sdk == ("prim", "str"):
            return "sdk_wider"
        return "incomparable"
    if sdk_kind == "base64":
        if spec == ("prim", "str"):
            return "sdk_narrower"
        return "incomparable"
    if spec_kind == "url" and sdk_kind == "url":
        # Not equal, so one side is file-only: AnyUrl accepts more than FileUrl.
        return "sdk_narrower" if sdk[1] == "file" else "sdk_wider"
    if spec_kind == "url" and sdk == ("prim", "str"):
        return "sdk_wider"
    if spec == ("prim", "str") and sdk_kind == "url":
        return "sdk_narrower"
    if spec_kind == "list" and sdk_kind == "list":
        return compat(spec[1], sdk[1])
    if spec_kind == "dict" and sdk_kind == "dict":
        key = compat(spec[1], sdk[1])
        value = compat(spec[2], sdk[2])
        ranking = {"incomparable": 3, "sdk_narrower": 2, "sdk_wider": 1, "equal": 0}
        worst = key if ranking[key] >= ranking[value] else value
        return worst
    # model-vs-model with different names, model-vs-non-model, opaque,
    # recursive markers with different names: the algebra cannot relate them.
    return "incomparable"


def _is_model(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseModel)


GapPaths = frozenset[tuple[str, str, str | None]]


def gap_paths(entries: list[AllowlistEntry]) -> GapPaths:
    """(oracle, def, field-or-None) paths whose type/requiredness checks are skipped."""
    return frozenset((e.oracle, e.name, e.field) for e in entries if e.category == "schema-gap")


def compare_oracle(oracle: str, gaps: GapPaths = frozenset()) -> list[Finding]:
    """Run the per-oracle checks for one oracle module."""
    module = oracle_module(oracle)
    findings: list[Finding] = []
    spec_defs: tuple[str, ...] = module.SPEC_DEFS
    for def_name in spec_defs:
        spec_obj = getattr(module, def_name)
        sdk_name = resolve_sdk_name(oracle, def_name)
        sdk_obj = sdk_lookup(sdk_name)
        if sdk_obj is None:
            findings.append(
                Finding(
                    check="SPEC-TYPE-MISSING",
                    oracle=oracle,
                    name=def_name,
                    field=None,
                    detail=f"no SDK counterpart named {sdk_name!r}",
                )
            )
            continue
        if _is_model(spec_obj) and _is_model(sdk_obj):
            findings.extend(_compare_models(oracle, def_name, spec_obj, sdk_obj, gaps))
        elif (oracle, def_name, None) not in gaps:
            spec_sig = sig(spec_obj, sdk=False)
            sdk_sig = sig(sdk_obj, sdk=True)
            findings.extend(_type_finding(oracle, def_name, None, spec_sig, sdk_sig))
    findings.sort(key=lambda f: (f.name, f.field or "", f.check))
    return findings


def _type_finding(oracle: str, name: str, field: str | None, spec_sig: Sig, sdk_sig: Sig) -> list[Finding]:
    relation = compat(spec_sig, sdk_sig)
    if relation == "equal":
        return []
    check = {
        "sdk_narrower": "TYPE-NARROWER",
        "sdk_wider": "TYPE-WIDER",
        "incomparable": "TYPE-INCOMPARABLE",
    }[relation]
    return [Finding(check=check, oracle=oracle, name=name, field=field, detail=f"spec={spec_sig} sdk={sdk_sig}")]


def _compare_models(
    oracle: str,
    def_name: str,
    spec_model: type[BaseModel],
    sdk_model: type[BaseModel],
    gaps: GapPaths,
) -> list[Finding]:
    findings: list[Finding] = []
    spec_fields = wire_fields(spec_model)
    sdk_fields = wire_fields(sdk_model)
    for wire_name, spec_info in spec_fields.items():
        if wire_name not in sdk_fields:
            findings.append(
                Finding(
                    check="SPEC-FIELD-MISSING",
                    oracle=oracle,
                    name=def_name,
                    field=wire_name,
                    detail=f"oracle field ({'required' if spec_info.is_required() else 'optional'}) absent on SDK "
                    f"{sdk_model.__name__}",
                )
            )
            continue
        if (oracle, def_name, wire_name) in gaps:
            continue
        sdk_info = sdk_fields[wire_name]
        if sdk_info.is_required() and not spec_info.is_required():
            findings.append(
                Finding(
                    check="SDK-REQUIRED-NOT-IN-SPEC",
                    oracle=oracle,
                    name=def_name,
                    field=wire_name,
                    detail="SDK requires this field; the oracle has it optional",
                )
            )
        elif spec_info.is_required() and not sdk_info.is_required():
            findings.append(
                Finding(
                    check="SPEC-FIELD-OPTIONAL-IN-SDK",
                    oracle=oracle,
                    name=def_name,
                    field=wire_name,
                    detail="oracle requires this field; the SDK has it optional",
                )
            )
        spec_sig = sig(spec_info.annotation, sdk=False)
        sdk_sig = sig(sdk_info.annotation, sdk=True)
        if not spec_info.is_required():
            spec_sig = _strip_optional_null(spec_sig)
        if not sdk_info.is_required():
            sdk_sig = _strip_optional_null(sdk_sig)
        findings.extend(_type_finding(oracle, def_name, wire_name, spec_sig, sdk_sig))
    for wire_name, sdk_info in sdk_fields.items():
        if wire_name in spec_fields or (oracle, def_name, wire_name) in gaps:
            continue
        if sdk_info.is_required():
            findings.append(
                Finding(
                    check="SDK-REQUIRED-NOT-IN-SPEC",
                    oracle=oracle,
                    name=def_name,
                    field=wire_name,
                    detail="SDK requires this field; this oracle version does not have it at all",
                )
            )
    return findings


def _sdk_public_names() -> list[str]:
    names: list[str] = list(mcp.types.__all__)
    return names


def _sdk_to_oracle_defs() -> dict[str, list[tuple[str, str]]]:
    """SDK attribute name -> [(oracle, def name)] for every def in every oracle."""
    pairing: dict[str, list[tuple[str, str]]] = {}
    for oracle in ORACLE_MODULES:
        module = oracle_module(oracle)
        spec_defs: tuple[str, ...] = module.SPEC_DEFS
        for def_name in spec_defs:
            sdk_name = resolve_sdk_name(oracle, def_name)
            pairing.setdefault(sdk_name, []).append((oracle, def_name))
    return pairing


def aggregated_findings() -> list[Finding]:
    """SDK-TYPE-PHANTOM and SDK-FIELD-PHANTOM, run once across all oracles."""
    findings: list[Finding] = []
    pairing = _sdk_to_oracle_defs()
    for sdk_name in _sdk_public_names():
        if sdk_name in SDK_MACHINERY:
            continue
        paired = pairing.get(sdk_name)
        if not paired:
            findings.append(
                Finding(
                    check="SDK-TYPE-PHANTOM",
                    oracle="sdk",
                    name=sdk_name,
                    field=None,
                    detail="SDK public type maps to no def in any oracle",
                )
            )
            continue
        sdk_obj = sdk_lookup(sdk_name)
        if not _is_model(sdk_obj):
            continue
        oracle_wire_names: set[str] = set()
        paired_models = False
        for oracle, def_name in paired:
            spec_obj = getattr(oracle_module(oracle), def_name)
            if _is_model(spec_obj):
                paired_models = True
                oracle_wire_names.update(wire_fields(spec_obj))
        if not paired_models:
            continue
        paired_defs = sorted({def_name for _, def_name in paired})
        findings.extend(
            Finding(
                check="SDK-FIELD-PHANTOM",
                oracle="sdk",
                name=sdk_name,
                field=wire_name,
                detail=f"SDK field's wire name appears in no oracle version of this def (paired: {paired_defs})",
            )
            for wire_name in wire_fields(sdk_obj)
            if wire_name not in oracle_wire_names
        )
    findings.sort(key=lambda f: (f.name, f.field or "", f.check))
    return findings


def all_findings(gaps: GapPaths = frozenset()) -> list[Finding]:
    """Every finding: per-oracle checks for each oracle plus the aggregated ones."""
    findings: list[Finding] = []
    for oracle in ORACLE_MODULES:
        findings.extend(compare_oracle(oracle, gaps))
    findings.extend(aggregated_findings())
    return findings


def schema_gap_applies(entry: AllowlistEntry) -> bool:
    """Whether a schema-gap exemption still matches the generated oracle.

    When a future ext-tasks pin repairs the schema (real `$ref`s, restored
    `required` arrays), regeneration changes the oracle, this returns False,
    the entry is stale, and the gate fails until it is removed.

    - VACUOUS-SCHEMA with no field: the def itself resolves to a signature
      containing `Any` (e.g. ``InputRequest: TypeAlias = Any``).
    - VACUOUS-SCHEMA with a field: somewhere in the def's model closure
      (the def plus its synthetic nested models, e.g. union variants and
      params objects) a field with that wire name has a signature containing
      `Any`. The closure is searched per wire name so unrelated open sites
      (``_meta``, completed-task ``result``) cannot keep the entry alive.
    - REQUIRED-UNVERIFIABLE: the def is a model with no required fields at
      all (its `required` array / intersection half was lost in the schema).
    """
    module = oracle_module(entry.oracle)
    obj = getattr(module, entry.name, None)
    if obj is None:
        return False
    if entry.check == "VACUOUS-SCHEMA":
        if entry.field is None:
            return not _is_model(obj) and _contains_any(sig(obj, sdk=False))
        return _closure_field_has_any(obj, entry.field)
    if entry.check == "REQUIRED-UNVERIFIABLE":
        if not _is_model(obj):
            return False
        return all(not info.is_required() for info in obj.model_fields.values())
    raise ValueError(f"not a schema-gap pseudo-check: {entry.check}")


def _closure_models(annotation: Any, seen: set[type[BaseModel]]) -> None:
    """Collect every pydantic model reachable from an annotation into `seen`."""
    if _is_model(annotation):
        model: type[BaseModel] = annotation
        if model in seen:
            return
        seen.add(model)
        for info in model.model_fields.values():
            _closure_models(info.annotation, seen)
        return
    if isinstance(annotation, TypeAliasType):
        _closure_models(annotation.__value__, seen)
        return
    for arg in get_args(annotation):
        _closure_models(arg, seen)


def _closure_field_has_any(obj: Any, wire_name: str) -> bool:
    seen: set[type[BaseModel]] = set()
    _closure_models(obj, seen)
    for model in seen:
        info = wire_fields(model).get(wire_name)
        if info is not None and _contains_any(sig(info.annotation, sdk=False)):
            return True
    return False


def _contains_any(s: Sig) -> bool:
    if s == _ANY:
        return True
    if s[0] in ("union",):
        return any(_contains_any(member) for member in s[1])
    if s[0] == "list":
        return _contains_any(s[1])
    if s[0] == "dict":
        return _contains_any(s[1]) or _contains_any(s[2])
    return False


@dataclass(frozen=True)
class Evaluation:
    """Outcome of matching findings against the allowlist."""

    new_hard: tuple[Finding, ...]
    stale_entries: tuple[AllowlistEntry, ...]
    allowlisted_hard: tuple[Finding, ...]
    soft: tuple[Finding, ...]


def evaluate(findings: list[Finding], entries: list[AllowlistEntry]) -> Evaluation:
    """Match findings against allowlist entries (both ratchet directions).

    A hard finding without a matching entry is new (gate fails). A
    non-schema-gap entry whose id matches no finding is stale (gate fails).
    Schema-gap entries never match findings; their staleness is decided by
    `schema_gap_applies`.
    """
    allowed_ids = {e.id for e in entries if e.category != "schema-gap"}
    finding_ids = {f.id for f in findings}
    new_hard = tuple(f for f in findings if f.hard and f.id not in allowed_ids)
    allowlisted_hard = tuple(f for f in findings if f.hard and f.id in allowed_ids)
    stale = tuple(entry for entry in entries if _entry_is_stale(entry, finding_ids))
    soft = tuple(f for f in findings if not f.hard)
    return Evaluation(
        new_hard=new_hard,
        stale_entries=stale,
        allowlisted_hard=allowlisted_hard,
        soft=soft,
    )


def _entry_is_stale(entry: AllowlistEntry, finding_ids: set[str]) -> bool:
    if entry.category == "schema-gap":
        return not schema_gap_applies(entry)
    return entry.id not in finding_ids
