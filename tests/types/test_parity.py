"""Assert every per-version surface model's wire fields are a subset of its `mcp_types` superset counterpart."""

from __future__ import annotations

import inspect
from types import ModuleType

import mcp_types as monolith
import mcp_types._types as _types
import mcp_types._v2025_11_25 as v2025_11_25
import mcp_types._v2026_07_28 as v2026_07_28
import pytest
from pydantic import BaseModel

SURFACES: tuple[ModuleType, ...] = (v2025_11_25, v2026_07_28)

# Envelope fields the monolith models on `mcp_types.jsonrpc` instead of on each request/notification.
ENVELOPE_FIELDS: frozenset[str] = frozenset({"jsonrpc", "id"})

# Surface classes whose monolith counterpart has a different name (key: "<surface_tail>.<ClassName>").
NAME_MAP: dict[str, type[BaseModel]] = {
    # _v2025_11_25
    "_v2025_11_25.Argument": monolith.CompletionArgument,
    "_v2025_11_25.Context": monolith.CompletionContext,
    "_v2025_11_25.Data": monolith.ElicitationRequiredErrorData,
    "_v2025_11_25.Elicitation": monolith.ElicitationCapability,
    "_v2025_11_25.Elicitation1": monolith.TasksElicitationCapability,
    "_v2025_11_25.ElicitationCompleteNotification": monolith.ElicitCompleteNotification,
    "_v2025_11_25.Params": monolith.CancelTaskRequestParams,
    "_v2025_11_25.Params1": monolith.ElicitCompleteNotificationParams,
    "_v2025_11_25.Params2": monolith.GetTaskPayloadRequestParams,
    "_v2025_11_25.Params3": monolith.GetTaskRequestParams,
    "_v2025_11_25.Error": monolith.ErrorData,
    "_v2025_11_25.JSONRPCErrorResponse": monolith.JSONRPCError,
    "_v2025_11_25.JSONRPCResultResponse": monolith.JSONRPCResponse,
    "_v2025_11_25.Prompts": monolith.PromptsCapability,
    "_v2025_11_25.Requests": monolith.ClientTasksRequestsCapability,
    "_v2025_11_25.Requests1": monolith.ServerTasksRequestsCapability,
    "_v2025_11_25.Resources": monolith.ResourcesCapability,
    "_v2025_11_25.Roots": monolith.RootsCapability,
    "_v2025_11_25.Sampling": monolith.SamplingCapability,
    "_v2025_11_25.Sampling1": monolith.TasksSamplingCapability,
    "_v2025_11_25.Tasks": monolith.ClientTasksCapability,
    "_v2025_11_25.Tasks1": monolith.ServerTasksCapability,
    "_v2025_11_25.Tools": monolith.TasksToolsCapability,
    "_v2025_11_25.Tools1": monolith.ToolsCapability,
    # _v2026_07_28
    "_v2026_07_28.Argument": monolith.CompletionArgument,
    "_v2026_07_28.Context": monolith.CompletionContext,
    "_v2026_07_28.Data": monolith.MissingRequiredClientCapabilityErrorData,
    "_v2026_07_28.Data1": monolith.UnsupportedProtocolVersionErrorData,
    "_v2026_07_28.Elicitation": monolith.ElicitationCapability,
    "_v2026_07_28.Error": monolith.ErrorData,
    "_v2026_07_28.JSONRPCErrorResponse": monolith.JSONRPCError,
    "_v2026_07_28.JSONRPCResultResponse": monolith.JSONRPCResponse,
    "_v2026_07_28.Prompts": monolith.PromptsCapability,
    "_v2026_07_28.Resources": monolith.ResourcesCapability,
    "_v2026_07_28.Sampling": monolith.SamplingCapability,
    "_v2026_07_28.Tools": monolith.ToolsCapability,
}

# Surface classes with no monolith equivalent (envelope wrappers, JSON-Schema fragments modelled as `dict`).
SKIP: frozenset[str] = frozenset(
    {
        # _v2025_11_25
        "_v2025_11_25.AnyOfItem",
        "_v2025_11_25.BooleanSchema",
        "_v2025_11_25.Error1",
        "_v2025_11_25.Icons",
        "_v2025_11_25.InputSchema",
        "_v2025_11_25.Items",
        "_v2025_11_25.Items1",
        "_v2025_11_25.LegacyTitledEnumSchema",
        "_v2025_11_25.Meta",
        "_v2025_11_25.NumberSchema",
        "_v2025_11_25.OneOfItem",
        "_v2025_11_25.OutputSchema",
        "_v2025_11_25.RequestedSchema",
        "_v2025_11_25.ResourceRequestParams",
        "_v2025_11_25.StringSchema",
        "_v2025_11_25.TaskAugmentedRequestParams",
        "_v2025_11_25.TitledMultiSelectEnumSchema",
        "_v2025_11_25.TitledSingleSelectEnumSchema",
        "_v2025_11_25.URLElicitationRequiredError",
        "_v2025_11_25.UntitledMultiSelectEnumSchema",
        "_v2025_11_25.UntitledSingleSelectEnumSchema",
        # _v2026_07_28
        "_v2026_07_28.AnyOfItem",
        "_v2026_07_28.BooleanSchema",
        "_v2026_07_28.CallToolResultResponse",
        "_v2026_07_28.ClientNotification",
        "_v2026_07_28.CompleteResultResponse",
        "_v2026_07_28.DiscoverResultResponse",
        "_v2026_07_28.Error1",
        "_v2026_07_28.Error2",
        "_v2026_07_28.Error3",
        "_v2026_07_28.GetPromptResultResponse",
        "_v2026_07_28.HeaderMismatchError",
        "_v2026_07_28.Icons",
        "_v2026_07_28.InputSchema",
        "_v2026_07_28.InternalError",
        "_v2026_07_28.InvalidParamsError",
        "_v2026_07_28.InvalidRequestError",
        "_v2026_07_28.Items",
        "_v2026_07_28.Items1",
        "_v2026_07_28.LegacyTitledEnumSchema",
        "_v2026_07_28.ListPromptsResultResponse",
        "_v2026_07_28.ListResourceTemplatesResultResponse",
        "_v2026_07_28.ListResourcesResultResponse",
        "_v2026_07_28.ListToolsResultResponse",
        "_v2026_07_28.MetaObject",
        "_v2026_07_28.MethodNotFoundError",
        "_v2026_07_28.MissingRequiredClientCapabilityError",
        "_v2026_07_28.NotificationMetaObject",
        "_v2026_07_28.NumberSchema",
        "_v2026_07_28.OneOfItem",
        "_v2026_07_28.OutputSchema",
        "_v2026_07_28.Params",
        "_v2026_07_28.ParseError",
        "_v2026_07_28.ReadResourceResultResponse",
        "_v2026_07_28.RequestMetaObject",
        "_v2026_07_28.RequestedSchema",
        "_v2026_07_28.ResourceRequestParams",
        "_v2026_07_28.ResultMetaObject",
        "_v2026_07_28.StringSchema",
        "_v2026_07_28.SubscriptionsListenResultMeta",
        "_v2026_07_28.TitledMultiSelectEnumSchema",
        "_v2026_07_28.TitledSingleSelectEnumSchema",
        "_v2026_07_28.UnsupportedProtocolVersionError",
        "_v2026_07_28.UntitledMultiSelectEnumSchema",
        "_v2026_07_28.UntitledSingleSelectEnumSchema",
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
