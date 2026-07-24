"""Assert every per-version surface model's wire fields are a subset of its `mcp_types` superset counterpart."""

from __future__ import annotations

import inspect
from types import ModuleType

import mcp_types as monolith
import mcp_types._types as _types
import mcp_types.jsonrpc as jsonrpc
import mcp_types.v2025_11_25 as v2025_11_25
import mcp_types.v2026_07_28 as v2026_07_28
import pytest
from mcp_types._wire_base import KeepRequiredNullable, admits_none
from pydantic import BaseModel

SURFACES: tuple[ModuleType, ...] = (v2025_11_25, v2026_07_28)

# Envelope fields the monolith models on `mcp_types.jsonrpc` instead of on each request/notification.
ENVELOPE_FIELDS: frozenset[str] = frozenset({"jsonrpc", "id"})

# Surface classes whose monolith counterpart has a different name (key: "<surface_tail>.<ClassName>").
NAME_MAP: dict[str, type[BaseModel]] = {
    # v2025_11_25
    "v2025_11_25.Argument": monolith.CompletionArgument,
    "v2025_11_25.Context": monolith.CompletionContext,
    "v2025_11_25.Data": monolith.ElicitationRequiredErrorData,
    "v2025_11_25.Elicitation": monolith.ElicitationCapability,
    "v2025_11_25.Elicitation1": monolith.TasksElicitationCapability,
    "v2025_11_25.ElicitationCompleteNotification": monolith.ElicitCompleteNotification,
    "v2025_11_25.Params": monolith.CancelTaskRequestParams,
    "v2025_11_25.Params1": monolith.ElicitCompleteNotificationParams,
    "v2025_11_25.Params2": monolith.GetTaskPayloadRequestParams,
    "v2025_11_25.Params3": monolith.GetTaskRequestParams,
    "v2025_11_25.Error": monolith.ErrorData,
    "v2025_11_25.JSONRPCErrorResponse": monolith.JSONRPCError,
    "v2025_11_25.JSONRPCResultResponse": monolith.JSONRPCResponse,
    "v2025_11_25.Prompts": monolith.PromptsCapability,
    "v2025_11_25.Requests": monolith.ClientTasksRequestsCapability,
    "v2025_11_25.Requests1": monolith.ServerTasksRequestsCapability,
    "v2025_11_25.Resources": monolith.ResourcesCapability,
    "v2025_11_25.Roots": monolith.RootsCapability,
    "v2025_11_25.Sampling": monolith.SamplingCapability,
    "v2025_11_25.Sampling1": monolith.TasksSamplingCapability,
    "v2025_11_25.Tasks": monolith.ClientTasksCapability,
    "v2025_11_25.Tasks1": monolith.ServerTasksCapability,
    "v2025_11_25.Tools": monolith.TasksToolsCapability,
    "v2025_11_25.Tools1": monolith.ToolsCapability,
    # v2026_07_28
    "v2026_07_28.Argument": monolith.CompletionArgument,
    "v2026_07_28.Context": monolith.CompletionContext,
    "v2026_07_28.Data": monolith.MissingRequiredClientCapabilityErrorData,
    "v2026_07_28.Data1": monolith.UnsupportedProtocolVersionErrorData,
    "v2026_07_28.Elicitation": monolith.ElicitationCapability,
    "v2026_07_28.Error": monolith.ErrorData,
    "v2026_07_28.JSONRPCErrorResponse": monolith.JSONRPCError,
    "v2026_07_28.JSONRPCResultResponse": monolith.JSONRPCResponse,
    "v2026_07_28.Prompts": monolith.PromptsCapability,
    "v2026_07_28.Resources": monolith.ResourcesCapability,
    "v2026_07_28.Sampling": monolith.SamplingCapability,
    "v2026_07_28.Tools": monolith.ToolsCapability,
}

# Surface classes with no monolith equivalent (envelope wrappers, JSON-Schema fragments modelled as `dict`).
SKIP: frozenset[str] = frozenset(
    {
        # v2025_11_25
        "v2025_11_25.AnyOfItem",
        "v2025_11_25.BooleanSchema",
        "v2025_11_25.Error1",
        "v2025_11_25.Icons",
        "v2025_11_25.InputSchema",
        "v2025_11_25.Items",
        "v2025_11_25.Items1",
        "v2025_11_25.LegacyTitledEnumSchema",
        "v2025_11_25.Meta",
        "v2025_11_25.NumberSchema",
        "v2025_11_25.OneOfItem",
        "v2025_11_25.OutputSchema",
        "v2025_11_25.RequestedSchema",
        "v2025_11_25.ResourceRequestParams",
        "v2025_11_25.StringSchema",
        "v2025_11_25.TaskAugmentedRequestParams",
        "v2025_11_25.TitledMultiSelectEnumSchema",
        "v2025_11_25.TitledSingleSelectEnumSchema",
        "v2025_11_25.URLElicitationRequiredError",
        "v2025_11_25.UntitledMultiSelectEnumSchema",
        "v2025_11_25.UntitledSingleSelectEnumSchema",
        # v2026_07_28
        "v2026_07_28.AnyOfItem",
        "v2026_07_28.BooleanSchema",
        "v2026_07_28.CallToolResultResponse",
        "v2026_07_28.ClientNotification",
        "v2026_07_28.CompleteResultResponse",
        "v2026_07_28.DiscoverResultResponse",
        "v2026_07_28.Error1",
        "v2026_07_28.Error2",
        "v2026_07_28.Error3",
        "v2026_07_28.GetPromptResultResponse",
        "v2026_07_28.HeaderMismatchError",
        "v2026_07_28.Icons",
        "v2026_07_28.InputSchema",
        "v2026_07_28.InternalError",
        "v2026_07_28.InvalidParamsError",
        "v2026_07_28.InvalidRequestError",
        "v2026_07_28.Items",
        "v2026_07_28.Items1",
        "v2026_07_28.LegacyTitledEnumSchema",
        "v2026_07_28.ListPromptsResultResponse",
        "v2026_07_28.ListResourceTemplatesResultResponse",
        "v2026_07_28.ListResourcesResultResponse",
        "v2026_07_28.ListToolsResultResponse",
        "v2026_07_28.MetaObject",
        "v2026_07_28.MethodNotFoundError",
        "v2026_07_28.MissingRequiredClientCapabilityError",
        "v2026_07_28.NotificationMetaObject",
        "v2026_07_28.NumberSchema",
        "v2026_07_28.OneOfItem",
        "v2026_07_28.OutputSchema",
        "v2026_07_28.Params",
        "v2026_07_28.ParseError",
        "v2026_07_28.ReadResourceResultResponse",
        "v2026_07_28.RequestMetaObject",
        "v2026_07_28.RequestedSchema",
        "v2026_07_28.ResourceRequestParams",
        "v2026_07_28.ResultMetaObject",
        "v2026_07_28.StringSchema",
        "v2026_07_28.SubscriptionsListenResultMeta",
        "v2026_07_28.TitledMultiSelectEnumSchema",
        "v2026_07_28.TitledSingleSelectEnumSchema",
        "v2026_07_28.UnsupportedProtocolVersionError",
        "v2026_07_28.UntitledMultiSelectEnumSchema",
        "v2026_07_28.UntitledSingleSelectEnumSchema",
    }
)

# Intentional gaps: (surface class, wire alias) -> reason the monolith omits the field.
_RESULT_TYPE_REASON = "resultType is declared on each concrete Result subclass, not the base"
FIELD_EXCEPTIONS: dict[tuple[type[BaseModel], str], str] = {
    (v2026_07_28.Result, "resultType"): _RESULT_TYPE_REASON,
    (v2026_07_28.PaginatedResult, "resultType"): _RESULT_TYPE_REASON,
    (v2026_07_28.CacheableResult, "resultType"): _RESULT_TYPE_REASON,
}


def _wire_aliases(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def _surface_classes(module: ModuleType) -> list[tuple[str, type[BaseModel]]]:
    tail = module.__name__.rsplit(".", 1)[-1]
    out: list[tuple[str, type[BaseModel]]] = []
    for name, obj in vars(module).items():
        if not (inspect.isclass(obj) and issubclass(obj, BaseModel)):
            continue
        if obj.__module__ != module.__name__ or obj.__name__ != name:
            continue  # re-export or alias to another model
        if getattr(obj, "__pydantic_root_model__", False):
            continue  # RootModel alias wrapper; the field-subset property does not apply
        out.append((f"{tail}.{name}", obj))
    return out


def _matched_pairs() -> list[tuple[str, type[BaseModel], type[BaseModel]]]:
    pairs: list[tuple[str, type[BaseModel], type[BaseModel]]] = []
    for module in SURFACES:
        for qualname, surface_cls in _surface_classes(module):
            if qualname in SKIP:
                continue
            mono_cls = (
                NAME_MAP.get(qualname)
                or getattr(monolith, surface_cls.__name__, None)
                or getattr(_types, surface_cls.__name__, None)
            )
            assert isinstance(mono_cls, type) and issubclass(mono_cls, BaseModel), qualname
            pairs.append((qualname, surface_cls, mono_cls))
    return pairs


@pytest.mark.parametrize(
    "qualname,surface_cls,mono_cls", _matched_pairs(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_monolith_is_superset_of_surface_fields(
    qualname: str, surface_cls: type[BaseModel], mono_cls: type[BaseModel]
) -> None:
    surface_fields = _wire_aliases(surface_cls) - ENVELOPE_FIELDS
    excused = {alias for (cls, alias) in FIELD_EXCEPTIONS if cls is surface_cls}
    missing = surface_fields - _wire_aliases(mono_cls) - excused
    assert not missing, f"{qualname}: monolith {mono_cls.__name__} missing wire fields {sorted(missing)}"


# Monolith model classes intentionally kept out of `mcp_types.__all__`.
PRIVATE_MONOLITH_MODELS: frozenset[str] = frozenset(
    {
        "MCPModel",  # internal base; users subclass the concrete spec types instead
    }
)


def test_every_public_monolith_model_is_exported_from_mcp_types() -> None:
    defined = {
        name
        for name, obj in vars(_types).items()
        if name.isidentifier()  # skip pydantic's `Request[...]` generic-alias entries
        and not name.startswith("_")
        and inspect.isclass(obj)
        and issubclass(obj, BaseModel)
        and obj.__module__ == _types.__name__
    }
    missing = defined - set(monolith.__all__) - PRIVATE_MONOLITH_MODELS
    assert not missing, f"_types models not in mcp_types.__all__: {sorted(missing)}"


def _models_with_a_required_nullable_field() -> list[tuple[str, type[BaseModel], frozenset[str]]]:
    """Every model with a required field whose value may be `None`, and those fields' aliases.

    A bare `Any` counts: the schema declares those properties with no type at all, so null
    is a legal value for them. Root models do not: `exclude_none` dumps their root value
    directly rather than omitting a key, so they cannot lose it.
    """
    found: list[tuple[str, type[BaseModel], frozenset[str]]] = []
    for module in (_types, jsonrpc, *SURFACES):
        for name, obj in vars(module).items():
            if not name.isidentifier():
                continue  # pydantic's `Request[...]` generic-alias entries; the concrete classes follow
            if not (inspect.isclass(obj) and issubclass(obj, BaseModel)) or obj.__module__ != module.__name__:
                continue
            if getattr(obj, "__pydantic_root_model__", False):
                continue
            nullable_required = frozenset(
                field.serialization_alias or field.alias or field_name
                for field_name, field in obj.model_fields.items()
                if field.is_required() and admits_none(field.annotation)
            )
            if nullable_required:
                found.append((f"{module.__name__}.{name}", obj, nullable_required))
    # An empty list would parametrize away to nothing and pass in silence.
    assert found, "discovery found no required-nullable fields at all; the walk is broken"
    return found


@pytest.mark.parametrize(
    "qualname,cls,nullable_required",
    _models_with_a_required_nullable_field(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_models_with_a_required_nullable_field_survive_an_exclude_none_dump(
    qualname: str, cls: type[BaseModel], nullable_required: frozenset[str]
) -> None:
    """`exclude_none=True` would drop such a field, leaving a body that fails its own schema.

    `KeepRequiredNullable` puts it back. This walk deliberately shares `admits_none` with the
    runtime, so it is a consistency check rather than an oracle: what it catches is a model the
    generator's independent schema-side rule (`_admits_null`) failed to give the base, or a
    hand-written model nobody remembered. A spelling both rules miss is caught by neither, and
    only an end-to-end test of that message would find it.
    """
    assert issubclass(cls, KeepRequiredNullable), (
        f"{qualname} needs the KeepRequiredNullable base. For a generated model, regenerate the "
        "surface packages; if that changes nothing, the schema spelling of this field is one "
        "`_admits_null` in scripts/gen_surface_types.py does not recognise. Hand-written models "
        "in _types.py and jsonrpc.py take the base directly."
    )
    instance = cls.model_construct(**dict.fromkeys(cls.model_fields))
    dumped = instance.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert nullable_required <= dumped.keys()
    assert all(dumped[alias] is None for alias in nullable_required)


def test_every_surface_class_is_accounted_for() -> None:
    monolith_models = {
        name
        for name, obj in (vars(monolith) | vars(_types)).items()
        if inspect.isclass(obj) and issubclass(obj, BaseModel)
    }
    surface = {q: cls.__name__ for module in SURFACES for q, cls in _surface_classes(module)}
    auto_matched = {q for q, name in surface.items() if name in monolith_models}
    unmapped = surface.keys() - auto_matched - NAME_MAP.keys() - SKIP
    assert not unmapped, f"surface classes with no mapping: {sorted(unmapped)}"
    stale = (NAME_MAP.keys() | SKIP) - surface.keys()
    assert not stale, f"stale NAME_MAP/SKIP entries: {sorted(stale)}"


def test_keep_required_nullable_only_restores_what_exclude_none_removed() -> None:
    """The base puts back a required null, and leaves every other dump mode alone.

    SDK-defined: `exclude`/`include` say the caller does not want the field at all, and a dump
    without `exclude_none` never lost it, so neither case is the base's to fix.
    """
    task = _types.Task(task_id="t1", status="working", created_at="x", last_updated_at="y", ttl=None)

    assert task.model_dump(by_alias=True, exclude_none=True)["ttl"] is None
    assert "ttl" not in task.model_dump(by_alias=True, exclude_none=True, exclude={"ttl"})
    assert task.model_dump(by_alias=True, exclude_none=True, include={"task_id"}) == {"taskId": "t1"}
    # Without exclude_none nothing was dropped, so the wrap passes the dump through untouched.
    assert task.model_dump(by_alias=True)["statusMessage"] is None
    # The restored key follows the caller's alias choice rather than always using the wire spelling.
    assert "ttl" in task.model_dump(exclude_none=True)
