"""Resolver dependency injection for MCPServer tools.

A tool parameter annotated `Annotated[T, Resolve(fn)]` is filled by running the
resolver `fn` before the tool body, instead of from the LLM-supplied arguments.
Resolvers form a DAG: a resolver may declare its own `Resolve(...)` dependencies,
take tool arguments by name, and take the `Context`. A resolver may return
`Elicit[T]` to ask the client; the framework runs the elicitation and injects the
answer.

Whether the consumer receives the unwrapped model or the full
`ElicitationResult` union is decided by the consumer's annotation:

- `Annotated[T, Resolve(fn)]` -> unwrapped `T`; decline/cancel aborts the call.
- `Annotated[ElicitationResult[T], Resolve(fn)]` (or a specific member) -> the
  full outcome; the consumer branches on accept/decline/cancel.

Each resolver runs at most once per `tools/call` (memoized by function identity).
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Generic, cast, get_args, get_origin

import anyio.to_thread
from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    ElicitationResult,
)
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import InvalidSignature, ToolError
from mcp.shared._callable_inspection import is_async_callable

T = TypeVar("T", bound=BaseModel)

# The union members the framework injects when a consumer opts into the outcome.
_ELICITATION_RESULT_MEMBERS = (AcceptedElicitation, DeclinedElicitation, CancelledElicitation)


class Resolve:
    """Marker for `Annotated[T, Resolve(fn)]`: fill the parameter by running `fn`."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self.fn = fn


class Elicit(Generic[T]):
    """A resolver's request to ask the client.

    Returned from a resolver to signal that the value must be elicited. The
    framework runs `ctx.elicit(message, schema)` and injects the outcome.
    """

    def __init__(self, message: str, schema: type[T]) -> None:
        self.message = message
        self.schema = schema


class _ParamPlan:
    """How to fill one resolver parameter, decided once at registration."""

    kind: str  # "context" | "resolve" | "by_name"
    resolve: Resolve | None
    wants_union: bool

    def __init__(self, kind: str, resolve: Resolve | None = None, wants_union: bool = False) -> None:
        self.kind = kind
        self.resolve = resolve
        self.wants_union = wants_union


class _ResolverPlan:
    """A resolver's parameters and whether it is async, analyzed once."""

    def __init__(self, fn: Callable[..., Any], params: dict[str, _ParamPlan], is_async: bool) -> None:
        self.fn = fn
        self.params = params
        self.is_async = is_async


def find_resolved_parameters(fn: Callable[..., Any]) -> dict[str, tuple[Resolve, bool]]:
    """Find parameters of `fn` annotated `Annotated[_, Resolve(...)]`.

    Returns a mapping of parameter name to `(Resolve, wants_union)`, where
    `wants_union` is True when the annotated type is an `ElicitationResult` member
    (the consumer wants the full outcome rather than the unwrapped model).
    """
    hints = typing.get_type_hints(fn, include_extras=True)
    resolved: dict[str, tuple[Resolve, bool]] = {}
    for name, annotation in hints.items():
        if get_origin(annotation) is not Annotated:
            continue
        type_arg, *metadata = get_args(annotation)
        marker = next((m for m in metadata if isinstance(m, Resolve)), None)
        if marker is not None:
            resolved[name] = (marker, _wants_union(type_arg))
    return resolved


def _wants_union(type_arg: Any) -> bool:
    """True when `type_arg` is an `ElicitationResult` member (or a union of them)."""
    members = get_args(type_arg) if get_origin(type_arg) is not None else (type_arg,)
    return any(isinstance(m, type) and issubclass(m, _ELICITATION_RESULT_MEMBERS) for m in members)


def build_resolver_plans(
    resolved_params: Mapping[str, tuple[Resolve, bool]],
    tool_arg_names: set[str],
) -> dict[int, _ResolverPlan]:
    """Statically analyze the resolver DAG rooted at a tool's resolved parameters.

    Raises:
        InvalidSignature: If a resolver has a cyclic dependency, or a resolver
            parameter cannot be classified (not a `Context`, a nested `Resolve`,
            or a tool argument by name).
    """
    plans: dict[int, _ResolverPlan] = {}

    def analyze(fn: Callable[..., Any], stack: tuple[int, ...]) -> None:
        key = id(fn)
        if key in stack:
            raise InvalidSignature(f"Resolver {fn.__name__!r} has a cyclic dependency")
        if key in plans:
            return

        hints = typing.get_type_hints(fn, include_extras=True)
        sig = inspect.signature(fn)
        params: dict[str, _ParamPlan] = {}
        nested: list[Callable[..., Any]] = []
        for param_name in sig.parameters:
            annotation = hints.get(param_name)
            if annotation is not None and _is_context_annotation(annotation):
                params[param_name] = _ParamPlan("context")
                continue
            marker, wants_union = _resolve_marker(annotation)
            if marker is not None:
                params[param_name] = _ParamPlan("resolve", marker, wants_union)
                nested.append(marker.fn)
                continue
            if param_name in tool_arg_names:
                params[param_name] = _ParamPlan("by_name")
                continue
            raise InvalidSignature(
                f"Resolver {fn.__name__!r} parameter {param_name!r} cannot be resolved: "
                "expected a Context, an Annotated[_, Resolve(...)], or a tool argument by name"
            )

        plans[key] = _ResolverPlan(fn, params, is_async_callable(fn))
        for dep in nested:
            analyze(dep, stack + (key,))

    for marker, _ in resolved_params.values():
        analyze(marker.fn, ())
    return plans


def _resolve_marker(annotation: Any) -> tuple[Resolve | None, bool]:
    if get_origin(annotation) is not Annotated:
        return None, False
    type_arg, *metadata = get_args(annotation)
    marker = next((m for m in metadata if isinstance(m, Resolve)), None)
    return marker, (_wants_union(type_arg) if marker is not None else False)


def _is_context_annotation(annotation: Any) -> bool:
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return isinstance(annotation, type) and issubclass(annotation, Context)


async def resolve_arguments(
    resolved_params: Mapping[str, tuple[Resolve, bool]],
    plans: Mapping[int, _ResolverPlan],
    tool_args: Mapping[str, Any],
    context: Context[Any, Any],
) -> dict[str, Any]:
    """Resolve every `Resolve`-marked tool parameter into a concrete value.

    Each resolver runs at most once (memoized by function identity). Returns a
    mapping of tool parameter name to the value to inject.

    Raises:
        ToolError: If an elicited value is declined or cancelled and the consumer
            asked for the unwrapped model (rather than the result union).
    """
    cache: dict[int, ElicitationResult[BaseModel]] = {}
    injected: dict[str, Any] = {}
    for name, (marker, wants_union) in resolved_params.items():
        outcome = await _resolve(marker.fn, plans, tool_args, context, cache)
        injected[name] = outcome if wants_union else _unwrap(outcome, name)
    return injected


async def _resolve(
    fn: Callable[..., Any],
    plans: Mapping[int, _ResolverPlan],
    tool_args: Mapping[str, Any],
    context: Context[Any, Any],
    cache: dict[int, ElicitationResult[BaseModel]],
) -> ElicitationResult[BaseModel]:
    key = id(fn)
    if key in cache:
        return cache[key]

    plan = plans[key]
    kwargs: dict[str, Any] = {}
    for param_name, param_plan in plan.params.items():
        if param_plan.kind == "context":
            kwargs[param_name] = context
        elif param_plan.kind == "by_name":
            kwargs[param_name] = tool_args[param_name]
        else:
            assert param_plan.resolve is not None
            dep_outcome = await _resolve(param_plan.resolve.fn, plans, tool_args, context, cache)
            kwargs[param_name] = dep_outcome if param_plan.wants_union else _unwrap(dep_outcome, param_name)

    if plan.is_async:
        result = await fn(**kwargs)
    else:
        result = await anyio.to_thread.run_sync(lambda: fn(**kwargs))

    outcome: ElicitationResult[BaseModel]
    if isinstance(result, Elicit):
        elicit = cast("Elicit[BaseModel]", result)
        outcome = await context.elicit(elicit.message, elicit.schema)
    else:
        outcome = AcceptedElicitation(data=result)

    cache[key] = outcome
    return outcome


def _unwrap(outcome: ElicitationResult[BaseModel], name: str) -> BaseModel:
    if isinstance(outcome, AcceptedElicitation):
        return outcome.data
    raise ToolError(f"Resolver for parameter {name!r} could not resolve: elicitation was {outcome.action}")


__all__ = [
    "Resolve",
    "Elicit",
    "ElicitationResult",
    "AcceptedElicitation",
    "DeclinedElicitation",
    "CancelledElicitation",
    "find_resolved_parameters",
    "build_resolver_plans",
    "resolve_arguments",
]
