"""Resolver dependency injection for MCPServer tools.

A tool parameter annotated `Annotated[T, Resolve(fn)]` is filled by running the
resolver `fn` before the tool body, instead of from the LLM-supplied arguments.
Resolvers form a DAG: a resolver may declare its own `Resolve(...)` dependencies,
take tool arguments by name, and take the `Context`. A resolver may return
`Elicit[T]` to ask the client; the framework runs the elicitation and injects the
answer.

The framework picks the elicitation transport from the negotiated protocol. At
>= 2026-07-28 it returns an `InputRequiredResult` carrying the batched questions
and resumes when the client retries with `input_responses`/`request_state`
(independent resolvers are asked in one round; a resolver depending on another's
answer is asked in a later round). At <= 2025-11-25 it issues a synchronous
`elicitation/create` request mid-call. Only *elicited* outcomes are carried in
`request_state` across rounds (so the user is asked each question once); a
resolver that returns a value without eliciting is pure and may re-run each round.

Whether the consumer receives the unwrapped model or the full
`ElicitationResult` union is decided by the consumer's annotation:

- `Annotated[T, Resolve(fn)]` -> unwrapped `T`; decline/cancel aborts the call.
- `Annotated[ElicitationResult[T], Resolve(fn)]` (or a specific member) -> the
  full outcome; the consumer branches on accept/decline/cancel.
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable, Hashable, Mapping
from typing import Annotated, Any, Generic, Literal, TypeGuard, get_args, get_origin

import anyio.to_thread
from mcp_types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequests,
    InputRequiredResult,
    InputResponses,
)
from mcp_types.version import is_version_at_least
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar

from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    ElicitationResult,
    render_elicitation_schema,
)
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import InvalidSignature, ToolError
from mcp.shared._callable_inspection import is_async_callable

T = TypeVar("T", bound=BaseModel)

# The union members the framework injects when a consumer opts into the outcome.
_ELICITATION_RESULT_MEMBERS = (AcceptedElicitation, DeclinedElicitation, CancelledElicitation)

# First protocol revision whose `tools/call` carries elicitation inside
# `InputRequiredResult` rather than as a standalone server-to-client request.
# Pinned (not `LATEST_MODERN_VERSION`, which moves when newer revisions are added).
_INPUT_REQUIRED_VERSION = "2026-07-28"
_STATE_VERSION = 1


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

    def __init__(
        self,
        fn: Callable[..., Any],
        params: dict[str, _ParamPlan],
        is_async: bool,
        elicit_schema: type[BaseModel] | None,
    ) -> None:
        self.fn = fn
        self.params = params
        self.is_async = is_async
        # The `T` from the resolver's `Elicit[T]` return arm, if annotated. Used to
        # re-validate an outcome restored from `request_state` into a model.
        self.elicit_schema = elicit_schema


def _type_hints(fn: Callable[..., Any]) -> dict[str, Any]:
    """Resolve type hints for a function or a callable object.

    `typing.get_type_hints` raises on a callable *instance*; fall back to its
    `__call__`. Returns an empty mapping when hints cannot be resolved, matching
    `find_context_parameter`'s tolerance so callables without annotations (or with
    unresolvable ones) simply have no resolved parameters.
    """
    target = fn if inspect.isroutine(fn) else getattr(type(fn), "__call__", fn)
    try:
        return typing.get_type_hints(target, include_extras=True)
    except Exception:
        return {}


def _resolver_name(fn: Callable[..., Any]) -> str:
    """Best-effort display name for error messages (callable objects lack `__name__`)."""
    return getattr(fn, "__name__", None) or type(fn).__name__


def find_resolved_parameters(fn: Callable[..., Any]) -> dict[str, tuple[Resolve, bool]]:
    """Find parameters of `fn` annotated `Annotated[_, Resolve(...)]`.

    Returns a mapping of parameter name to `(Resolve, wants_union)`, where
    `wants_union` is True when the annotated type is an `ElicitationResult` member
    (the consumer wants the full outcome rather than the unwrapped model).
    """
    hints = _type_hints(fn)
    resolved: dict[str, tuple[Resolve, bool]] = {}
    for name in inspect.signature(fn).parameters:
        annotation = hints.get(name)
        if get_origin(annotation) is not Annotated:
            continue
        type_arg, *metadata = get_args(annotation)
        marker = next((m for m in metadata if isinstance(m, Resolve)), None)
        if marker is not None:
            resolved[name] = (marker, _wants_union(type_arg))
    return resolved


def _elicit_return_schema(return_annotation: Any) -> type[BaseModel] | None:
    """Extract `T` from a resolver return type's `Elicit[T]` arm, if present.

    Handles a bare `-> Elicit[T]` and a `-> T | Elicit[T]` union. Lets an elicited
    outcome restored from `request_state` (a plain dict) be re-validated into its
    model so dependent resolvers and tools receive a typed value.
    """
    # A bare `Elicit[T]` is itself a candidate; a union contributes its members.
    candidates = get_args(return_annotation) if _is_union(return_annotation) else (return_annotation,)
    for candidate in candidates:
        if get_origin(candidate) is Elicit:
            schema = get_args(candidate)[0]
            if isinstance(schema, type) and issubclass(schema, BaseModel):  # pragma: no branch
                return schema
    return None


def _is_union(annotation: Any) -> bool:
    return get_origin(annotation) in (typing.Union, types.UnionType)


def _wants_union(type_arg: Any) -> bool:
    """True when `type_arg` is an `ElicitationResult` member (or a union of them).

    Handles the bare `ElicitationResult[T]` alias (a `TypeAliasType` carrying the
    union on `__value__`), an explicit `AcceptedElicitation[T] | ... ` union, and a
    single member.
    """
    origin = get_origin(type_arg)
    value = getattr(origin, "__value__", None)
    if value is not None:
        type_arg = value
    members = get_args(type_arg) if get_origin(type_arg) is not None else (type_arg,)
    return any(isinstance(m, type) and issubclass(m, _ELICITATION_RESULT_MEMBERS) for m in members)


def _resolver_key(fn: Callable[..., Any]) -> Hashable:
    """Identity key for memoizing a resolver.

    A bound method - pure-python (`inspect.ismethod`) or built-in (e.g. `obj.meth`
    on a C-extension type) - is recreated on each attribute access, so `id(fn)`
    differs every time. Key it by its underlying function (or name) plus its
    `__self__` identity so `auth.login` referenced in two places memoizes to one
    call. Everything else keys by `id`, so two distinct callables never collide
    even if they compare equal.
    """
    bound_self = getattr(fn, "__self__", None)
    if bound_self is not None:
        # `__func__` (pure-python) has a stable identity; built-ins expose only a
        # stable `__name__`. Use the function's id or the name's value accordingly.
        func = getattr(fn, "__func__", None)
        underlying: Hashable = id(func) if func is not None else getattr(fn, "__name__", id(fn))
        return (underlying, id(bound_self))
    return id(fn)


def build_resolver_plans(
    resolved_params: Mapping[str, tuple[Resolve, bool]],
    tool_arg_names: set[str],
) -> dict[Hashable, _ResolverPlan]:
    """Statically analyze the resolver DAG rooted at a tool's resolved parameters.

    Raises:
        InvalidSignature: If a resolver has a cyclic dependency, or a resolver
            parameter cannot be classified (not a `Context`, a nested `Resolve`,
            or a tool argument by name).
    """
    plans: dict[Hashable, _ResolverPlan] = {}

    def analyze(fn: Callable[..., Any], stack: tuple[Hashable, ...]) -> None:
        key = _resolver_key(fn)
        if key in stack:
            raise InvalidSignature(f"Resolver {_resolver_name(fn)!r} has a cyclic dependency")
        if key in plans:
            return

        hints = _type_hints(fn)
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
                f"Resolver {_resolver_name(fn)!r} parameter {param_name!r} cannot be resolved: "
                "expected a Context, an Annotated[_, Resolve(...)], or a tool argument by name"
            )

        plans[key] = _ResolverPlan(fn, params, is_async_callable(fn), _elicit_return_schema(hints.get("return")))
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
    candidates = get_args(annotation) if get_origin(annotation) is not None else (annotation,)
    return any(isinstance(c, type) and issubclass(c, Context) for c in candidates)


class _Pending(Exception):
    """Internal: a resolver needs client input not yet available this round."""


class _Resolution:
    """Per-`tools/call` resolution state, shared across the DAG walk.

    `input_required` selects the transport: at >= 2026-07-28 elicitations are
    batched into `pending` and surfaced as an `InputRequiredResult`; at older
    revisions each `Elicit` is answered synchronously via `ctx.elicit`.
    """

    def __init__(
        self,
        plans: Mapping[Hashable, _ResolverPlan],
        tool_args: Mapping[str, Any],
        context: Context[Any, Any],
        input_required: bool,
    ) -> None:
        self.plans = plans
        self.tool_args = tool_args
        self.context = context
        self.input_required = input_required
        self.answers: InputResponses = context.input_responses or {} if input_required else {}
        self.state = _decode_state(context.request_state) if input_required else {}
        # In-call dedup keyed by resolver identity (distinguishes two instances of
        # the same bound method); `elicited` holds only outcomes that came from an
        # elicitation, keyed by their wire key - these are what `request_state`
        # persists, since pure resolvers are cheap to re-run each round.
        self.cache: dict[Hashable, ElicitationResult[Any]] = {}
        self.elicited: dict[str, ElicitationResult[Any]] = {}
        self.pending: InputRequests = {}


def _state_key(fn: Callable[..., Any]) -> str:
    """Process-stable wire key for a resolver's elicitation.

    `id(fn)` isn't stable across `input_required` rounds, so key `input_requests` /
    `request_state` by `module:qualname`. Bound methods add their `__self__` id so
    two instances of the same method get distinct questions and stored outcomes
    (the registered `Resolve(...)` holds the instance for the call's lifetime).
    """
    base = f"{getattr(fn, '__module__', '')}:{getattr(fn, '__qualname__', fn)!s}"
    bound_self = getattr(fn, "__self__", None)
    return f"{base}#{id(bound_self)}" if bound_self is not None else base


async def resolve_arguments(
    resolved_params: Mapping[str, tuple[Resolve, bool]],
    plans: Mapping[Hashable, _ResolverPlan],
    tool_args: Mapping[str, Any],
    context: Context[Any, Any],
) -> dict[str, Any] | InputRequiredResult:
    """Resolve every `Resolve`-marked tool parameter into a concrete value.

    Returns the mapping of tool parameter name to injected value when every
    resolver is satisfied. When a resolver still needs client input (and the
    negotiated protocol is >= 2026-07-28), returns an `InputRequiredResult`
    carrying the batched questions instead; the tool body is not run.

    An eliciting resolver asks its question once - its answer is carried in
    `request_state` across rounds - while a resolver that resolves without
    eliciting is pure and may re-run on each round.

    Raises:
        ToolError: If an elicited value is declined or cancelled and the consumer
            asked for the unwrapped model (rather than the result union).
    """
    # `ctx.protocol_version` is `None` outside an active request: `MCPServer.call_tool()`
    # called directly builds such a `Context`, and a tool whose resolvers never elicit
    # must still work there. A missing version means the synchronous (non-input_required)
    # transport, which never reaches a server-to-client request anyway.
    res = _Resolution(plans, tool_args, context, uses_input_required(context.protocol_version))
    injected: dict[str, Any] = {}
    for name, (marker, wants_union) in resolved_params.items():
        try:
            outcome = await _resolve(marker.fn, res)
        except _Pending:
            continue
        injected[name] = outcome if wants_union else _unwrap(outcome, name)

    if res.pending:
        return InputRequiredResult(input_requests=res.pending, request_state=_encode_state(res.elicited))
    return injected


async def _resolve(fn: Callable[..., Any], res: _Resolution) -> ElicitationResult[Any]:
    """Resolve one resolver, deduped within the call by its resolver identity.

    Raises `_Pending` when the resolver (or one of its dependencies) needs client
    input that has not arrived yet.
    """
    cache_key = _resolver_key(fn)
    if cache_key in res.cache:
        return res.cache[cache_key]

    plan = res.plans[cache_key]
    wire_key = _state_key(fn)
    if wire_key in res.pending:
        # Already asked this round by another consumer; don't run the resolver again.
        raise _Pending
    if wire_key in res.state:
        outcome = _outcome_from_state(res.state[wire_key], plan.elicit_schema)
        res.cache[cache_key] = outcome
        return outcome

    kwargs: dict[str, Any] = {}
    dep_pending = False
    for param_name, param_plan in plan.params.items():
        if param_plan.kind == "context":
            kwargs[param_name] = res.context
        elif param_plan.kind == "by_name":
            kwargs[param_name] = res.tool_args[param_name]
        else:
            assert param_plan.resolve is not None
            try:
                # Visit every dependency so independent ones that need input are all
                # collected into `res.pending` and batched into a single round.
                dep_outcome = await _resolve(param_plan.resolve.fn, res)
            except _Pending:
                dep_pending = True
                continue
            kwargs[param_name] = dep_outcome if param_plan.wants_union else _unwrap(dep_outcome, param_name)
    if dep_pending:
        raise _Pending

    result: Any
    if plan.is_async:
        result = await fn(**kwargs)
    else:
        result = await anyio.to_thread.run_sync(lambda: fn(**kwargs))

    if _is_elicit(result):
        outcome = await _elicit(result, wire_key, res)
        res.elicited[wire_key] = outcome
    else:
        # A resolver may return any type (not just `BaseModel`), so accept it as the
        # outcome without validating against the schema bound. Plain outcomes are not
        # persisted in `request_state`; the resolver re-runs next round instead.
        outcome = _accepted(result)

    res.cache[cache_key] = outcome
    return outcome


async def _elicit(elicit: Elicit[Any], key: str, res: _Resolution) -> ElicitationResult[Any]:
    """Turn a resolver's `Elicit` into an outcome via the negotiated transport."""
    if not res.input_required:
        return await res.context.elicit(elicit.message, elicit.schema)

    answer = res.answers.get(key)
    if answer is None:
        res.pending[key] = _elicit_request(elicit)
        raise _Pending
    if not isinstance(answer, ElicitResult):
        raise ToolError(f"Resolver {key!r} received a non-elicitation response")
    if answer.action == "accept":
        if answer.content is None:
            raise ToolError(f"Resolver {key!r} received an accepted elicitation with no content")
        return AcceptedElicitation(data=elicit.schema.model_validate(answer.content))
    if answer.action == "decline":
        return DeclinedElicitation()
    return CancelledElicitation()


def _unwrap(outcome: ElicitationResult[Any], name: str) -> Any:
    if isinstance(outcome, AcceptedElicitation):
        return outcome.data
    raise ToolError(f"Resolver for parameter {name!r} could not resolve: elicitation was {outcome.action}")


def _is_elicit(value: Any) -> TypeGuard[Elicit[Any]]:
    """Runtime narrow of a resolver's return value to a (parameter-erased) `Elicit`."""
    return isinstance(value, Elicit)


def _accepted(data: Any) -> AcceptedElicitation[Any]:
    """Wrap a resolved value as an accepted outcome without schema validation.

    A resolver may return any type (the schema bound only constrains `Elicit[T]`),
    and a value restored from `request_state` is already validated.
    """
    return AcceptedElicitation[Any].model_construct(data=data)


def uses_input_required(protocol_version: str | None) -> bool:
    """True when this request must elicit via `InputRequiredResult` (>= 2026-07-28).

    Older revisions still carry a standalone `elicitation/create` server-to-client
    request, so the framework keeps the synchronous `ctx.elicit()` path for them.
    """
    return protocol_version is not None and is_version_at_least(protocol_version, _INPUT_REQUIRED_VERSION)


def _elicit_request(elicit: Elicit[Any]) -> ElicitRequest:
    """Render an `Elicit[T]` as the embedded `elicitation/create` request for `input_requests`."""
    json_schema = render_elicitation_schema(elicit.schema)
    return ElicitRequest(params=ElicitRequestFormParams(message=elicit.message, requested_schema=json_schema))


class _StateEntry(BaseModel):
    """One resolver's recorded outcome inside `request_state`."""

    action: Literal["accept", "decline", "cancel"]
    data: Any = None


class _State(BaseModel):
    """The decoded `request_state`: resolver outcomes from earlier rounds."""

    v: int
    outcomes: dict[str, _StateEntry] = {}


def _decode_state(request_state: str | None) -> dict[str, _StateEntry]:
    """Decode the per-call resolution progress from `request_state`.

    `request_state` is client-trusted (integrity sealing is a follow-up); validate
    it through `_State` and treat anything malformed as "no progress yet".
    """
    if not request_state:
        return {}
    try:
        state = _State.model_validate_json(request_state)
    except ValidationError:
        return {}
    return state.outcomes if state.v == _STATE_VERSION else {}


def _encode_state(outcomes: Mapping[str, ElicitationResult[Any]]) -> str:
    """Encode resolved outcomes (keyed by resolver path) for the next round."""
    entries: dict[str, _StateEntry] = {}
    for path, outcome in outcomes.items():
        data = outcome.data if isinstance(outcome, AcceptedElicitation) else None
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        entries[path] = _StateEntry(action=outcome.action, data=data)
    return _State(v=_STATE_VERSION, outcomes=entries).model_dump_json()


def _outcome_from_state(entry: _StateEntry, schema: type[BaseModel] | None) -> ElicitationResult[Any]:
    """Rebuild an `ElicitationResult` from a decoded `request_state` entry."""
    if entry.action == "decline":
        return DeclinedElicitation()
    if entry.action == "cancel":
        return CancelledElicitation()
    data = entry.data
    if schema is not None and isinstance(data, dict):
        data = schema.model_validate(data)
    return _accepted(data)


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
