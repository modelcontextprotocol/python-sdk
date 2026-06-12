"""Comparison library for the spec-oracle burn-down harness.

Compares the generated, SHA-pinned oracle modules in this directory against the
SDK's hand-curated types (`mcp.types`, with `mcp.types.jsonrpc` as a secondary
search module). Every divergence becomes a `Finding`; hard findings fail the
gate in `test_burndown.py` unless they are allowlisted in
`burndown_allowlist.json`, and allowlisted entries that no longer fire are
*stale* and also fail the gate (the two-way ratchet that makes the allowlist a
burn-down list rather than a suppression file).

Deliberate name divergences are read from `mcp.types._spec_names` — the SDK's
single in-tree record of them — rather than duplicated here: schema defs the
SDK models under a different name resolve through `SDK_TO_SCHEMA_RENAMES`,
schema defs the SDK deliberately does not model (`SCHEMA_NOT_MODELED`) are
skipped, and SDK names with no schema counterpart in any version
(`SDK_ONLY_NAMES`) are exempt from the phantom checks.

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
from mcp.types._spec_names import SCHEMA_NOT_MODELED, SDK_ONLY_NAMES, SDK_TO_SCHEMA_RENAMES

ORACLE_PACKAGE = "tests.spec_oracles"
ORACLE_MODULES: tuple[str, ...] = (
    "v2024_11_05",
    "v2025_03_26",
    "v2025_06_18",
    "v2025_11_25",
    "v2026_07_28",
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
CATEGORIES = frozenset({"not-yet-implemented", "deliberate-deviation", "suspected-sdk-bug"})

# Spec def name -> SDK attribute name, for deliberate SDK renames. Read from
# the SDK's divergence map (which records the SDK-name -> schema-name
# direction); NAME_MAP_BY_ORACLE overrides per oracle module.
NAME_MAP: dict[str, str] = {schema: sdk for sdk, schema in SDK_TO_SCHEMA_RENAMES.items()}
NAME_MAP_BY_ORACLE: dict[str, dict[str, str]] = {
    # The 2025-06-18 schema renamed ResourceReference to ResourceTemplateReference;
    # the SDK uses the new name for all versions. A schema-side rename across
    # versions, not an SDK divergence, so it lives here rather than in the
    # divergence map.
    "v2024_11_05": {"ResourceReference": "ResourceTemplateReference"},
    "v2025_03_26": {"ResourceReference": "ResourceTemplateReference"},
}

# SDK public names exempt from SDK-TYPE-PHANTOM, beyond the divergence map's
# SDK_ONLY_NAMES (named types with no schema counterpart): machinery that has
# no spec def on purpose. Anything less obvious belongs in the allowlist
# instead, where it stays visible in the burn-down report.
SDK_MACHINERY: frozenset[str] = frozenset(
    {
        # Protocol version constants (schema.ts constants, not $defs).
        "LATEST_PROTOCOL_VERSION",
        "DEFAULT_NEGOTIATED_VERSION",
        # Reserved `_meta` key string constants (spec prose, not $defs).
        "PROTOCOL_VERSION_META_KEY",
        "CLIENT_INFO_META_KEY",
        "CLIENT_CAPABILITIES_META_KEY",
        "LOG_LEVEL_META_KEY",
        # JSON-RPC version string constant.
        "JSONRPC_VERSION",
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
        # TypedDict plumbing for request _meta (the schema models the reserved
        # keys on RequestMetaObject, which the SDK deliberately does not model
        # as a type - see the divergence map).
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
        # Params classes lifted from inline (non-$defs) params objects.
        "CancelTaskRequestParams",
        "ElicitCompleteNotificationParams",
        "GetTaskPayloadRequestParams",
        "GetTaskRequestParams",
        # Models/aliases lifted from inline (non-$defs) schema objects.
        "Completion",  # CompleteResult.completion inline object
        "IncludeContext",  # CreateMessageRequest.params.includeContext inline enum
        "StopReason",  # CreateMessageResult.stopReason inline string union
    }
)

# The full SDK-TYPE-PHANTOM exemption set.
PHANTOM_EXEMPT: frozenset[str] = SDK_MACHINERY | SDK_ONLY_NAMES

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
    """One allowlisted finding."""

    id: str
    check: str
    oracle: str
    name: str
    field: str | None
    category: str
    reason: str
    track: str | None


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[AllowlistEntry]:
    """Load and validate the burn-down allowlist.

    Every entry pairs a category with a free-text reason that must stand on
    its own: ``not-yet-implemented`` marks a gap the burn-down will close,
    ``deliberate-deviation`` says why the SDK intentionally differs from the
    schema, and ``suspected-sdk-bug`` states the schema fact, the SDK behavior
    that disagrees with it, and where in the source tree the pending decision
    is recorded.
    """
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
        if entry.check not in HARD_CHECKS:
            raise ValueError(f"allowlist entry {entry.id!r}: only hard findings can be allowlisted")
        if not entry.reason.strip():
            raise ValueError(f"allowlist entry {entry.id!r}: empty reason")
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


def _normalize_model_name(name: str, *, sdk: bool) -> str:
    """Map SDK model names back to spec names so paired models compare equal."""
    return SDK_TO_SCHEMA_RENAMES.get(name, name) if sdk else name


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


def compare_oracle(oracle: str) -> list[Finding]:
    """Run the per-oracle checks for one oracle module."""
    module = oracle_module(oracle)
    findings: list[Finding] = []
    spec_defs: tuple[str, ...] = module.SPEC_DEFS
    for def_name in spec_defs:
        if def_name in SCHEMA_NOT_MODELED:
            continue
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
            findings.extend(_compare_models(oracle, def_name, spec_obj, sdk_obj))
        else:
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
        if wire_name in spec_fields:
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
    """SDK attribute name -> [(oracle, def name)] for every def in every oracle.

    Defs the SDK deliberately does not model are excluded: a not-modeled def
    must not silently satisfy an SDK name's pairing.
    """
    pairing: dict[str, list[tuple[str, str]]] = {}
    for oracle in ORACLE_MODULES:
        module = oracle_module(oracle)
        spec_defs: tuple[str, ...] = module.SPEC_DEFS
        for def_name in spec_defs:
            if def_name in SCHEMA_NOT_MODELED:
                continue
            sdk_name = resolve_sdk_name(oracle, def_name)
            pairing.setdefault(sdk_name, []).append((oracle, def_name))
    return pairing


def aggregated_findings() -> list[Finding]:
    """SDK-TYPE-PHANTOM and SDK-FIELD-PHANTOM, run once across all oracles."""
    findings: list[Finding] = []
    pairing = _sdk_to_oracle_defs()
    for sdk_name in _sdk_public_names():
        if sdk_name in PHANTOM_EXEMPT:
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


def all_findings() -> list[Finding]:
    """Every finding: per-oracle checks for each oracle plus the aggregated ones."""
    findings: list[Finding] = []
    for oracle in ORACLE_MODULES:
        findings.extend(compare_oracle(oracle))
    findings.extend(aggregated_findings())
    return findings


@dataclass(frozen=True)
class Evaluation:
    """Outcome of matching findings against the allowlist."""

    new_hard: tuple[Finding, ...]
    stale_entries: tuple[AllowlistEntry, ...]
    allowlisted_hard: tuple[Finding, ...]
    soft: tuple[Finding, ...]


def evaluate(findings: list[Finding], entries: list[AllowlistEntry]) -> Evaluation:
    """Match findings against allowlist entries (both ratchet directions).

    A hard finding without a matching entry is new (gate fails). An entry
    whose id matches no finding is stale (gate fails).
    """
    allowed_ids = {e.id for e in entries}
    finding_ids = {f.id for f in findings}
    new_hard = tuple(f for f in findings if f.hard and f.id not in allowed_ids)
    allowlisted_hard = tuple(f for f in findings if f.hard and f.id in allowed_ids)
    stale = tuple(entry for entry in entries if entry.id not in finding_ids)
    soft = tuple(f for f in findings if not f.hard)
    return Evaluation(
        new_hard=new_hard,
        stale_entries=stale,
        allowlisted_hard=allowlisted_hard,
        soft=soft,
    )
