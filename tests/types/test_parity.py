"""Assert every per-version surface model's wire fields are a subset of its `mcp_types` superset counterpart."""

from __future__ import annotations

import inspect
from types import ModuleType

import mcp_types as monolith
import mcp_types._types as _types
import mcp_types.v2025_11_25 as v2025_11_25
import mcp_types.v2026_07_28 as v2026_07_28
import pytest
from pydantic import BaseModel

SURFACES: tuple[ModuleType, ...] = (v2025_11_25, v2026_07_28)

# Envelope fields the monolith models on `mcp_types.jsonrpc` instead of on each request/notification.
ENVELOPE_FIELDS: frozenset[str] = frozenset({"jsonrpc", "id"})

# Surface classes whose monolith counterpart has a different name (key: "<surface_tail>.<ClassName>").
NAME_MAP: dict[str, type[BaseModel]] = {
    # v2025_11_25
    "v2025_11_25.AnyOfItem": monolith.EnumOption,
    "v2025_11_25.Argument": monolith.CompletionArgument,
    "v2025_11_25.Context": monolith.CompletionContext,
    "v2025_11_25.Data": monolith.ElicitationRequiredErrorData,
    "v2025_11_25.Elicitation": monolith.ElicitationCapability,
    "v2025_11_25.Elicitation1": monolith.TasksElicitationCapability,
    "v2025_11_25.ElicitationCompleteNotification": monolith.ElicitCompleteNotification,
    "v2025_11_25.Items": monolith.TitledMultiSelectEnumItems,
    "v2025_11_25.Items1": monolith.UntitledMultiSelectEnumItems,
    "v2025_11_25.OneOfItem": monolith.EnumOption,
    "v2025_11_25.Params": monolith.CancelTaskRequestParams,
    "v2025_11_25.Params1": monolith.ElicitCompleteNotificationParams,
    "v2025_11_25.Params2": monolith.GetTaskPayloadRequestParams,
    "v2025_11_25.Params3": monolith.GetTaskRequestParams,
    "v2025_11_25.RequestedSchema": monolith.ElicitRequestedSchema,
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
    "v2026_07_28.AnyOfItem": monolith.EnumOption,
    "v2026_07_28.Argument": monolith.CompletionArgument,
    "v2026_07_28.Context": monolith.CompletionContext,
    "v2026_07_28.Data": monolith.MissingRequiredClientCapabilityErrorData,
    "v2026_07_28.Data1": monolith.UnsupportedProtocolVersionErrorData,
    "v2026_07_28.Elicitation": monolith.ElicitationCapability,
    "v2026_07_28.Error": monolith.ErrorData,
    "v2026_07_28.Items": monolith.TitledMultiSelectEnumItems,
    "v2026_07_28.Items1": monolith.UntitledMultiSelectEnumItems,
    "v2026_07_28.JSONRPCErrorResponse": monolith.JSONRPCError,
    "v2026_07_28.JSONRPCResultResponse": monolith.JSONRPCResponse,
    "v2026_07_28.OneOfItem": monolith.EnumOption,
    "v2026_07_28.Prompts": monolith.PromptsCapability,
    "v2026_07_28.RequestedSchema": monolith.ElicitRequestedSchema,
    "v2026_07_28.Resources": monolith.ResourcesCapability,
    "v2026_07_28.Sampling": monolith.SamplingCapability,
    "v2026_07_28.Tools": monolith.ToolsCapability,
}

# Surface classes with no monolith equivalent (envelope wrappers, JSON-Schema fragments modelled as `dict`).
SKIP: frozenset[str] = frozenset(
    {
        # v2025_11_25
        "v2025_11_25.Error1",
        "v2025_11_25.Icons",
        "v2025_11_25.InputSchema",
        "v2025_11_25.Meta",
        "v2025_11_25.OutputSchema",
        "v2025_11_25.ResourceRequestParams",
        "v2025_11_25.TaskAugmentedRequestParams",
        "v2025_11_25.URLElicitationRequiredError",
        # v2026_07_28
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
        "v2026_07_28.ListPromptsResultResponse",
        "v2026_07_28.ListResourceTemplatesResultResponse",
        "v2026_07_28.ListResourcesResultResponse",
        "v2026_07_28.ListToolsResultResponse",
        "v2026_07_28.MetaObject",
        "v2026_07_28.MethodNotFoundError",
        "v2026_07_28.MissingRequiredClientCapabilityError",
        "v2026_07_28.NotificationMetaObject",
        "v2026_07_28.OutputSchema",
        "v2026_07_28.Params",
        "v2026_07_28.ParseError",
        "v2026_07_28.ReadResourceResultResponse",
        "v2026_07_28.RequestMetaObject",
        "v2026_07_28.ResourceRequestParams",
        "v2026_07_28.SubscriptionsListenResultMeta",
        "v2026_07_28.UnsupportedProtocolVersionError",
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
