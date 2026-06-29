"""Resolver dependency injection for MCPServer tools.

A tool parameter annotated `Annotated[T, Resolve(fn)]` is filled by running the
resolver `fn` before the tool body, instead of from the LLM-supplied arguments.
Resolvers form a DAG: a resolver may declare its own `Resolve(...)` dependencies,
take tool arguments by name, and take the `Context`. A resolver may return
`Elicit[T]` to ask the client; each question is asked once per call, but a
resolver that returns without eliciting is pure and may re-run each round.

Annotating the consumer `Annotated[ElicitationResult[T], Resolve(fn)]` (or a
specific member) injects the full accept/decline/cancel outcome; the bare `T`
form injects the unwrapped model and aborts the call on decline/cancel.
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable, Hashable, Mapping
from typing import Annotated, Any, Generic, Literal, TypeGuard, get_args, get_origin

import anyio.to_thread
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    ClientCapabilities,
    ElicitationCapability,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    FormElicitationCapability,
    InputRequests,
    InputRequiredResult,
    InputResponses,
    MissingRequiredClientCapabilityErrorData,
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
from mcp.shared.exceptions import MCPError

T = TypeVar("T", bound=BaseModel)

_ELICITATION_RESULT_MEMBERS = (AcceptedElicitation, DeclinedElicitation, CancelledElicitation)

# First revision carrying elicitation inside `InputRequiredResult`; pinned, not
# `LATEST_MODERN_VERSION`, which moves when newer revisions are added.
_INPUT_REQUIRED_VERSION = "2026-07-28"
_STATE_VERSION = 1


class Resolve:
    """Marker for `Annotated[T, Resolve(fn)]`: fill the parameter by running `fn`."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self.fn = fn


class Elicit(Generic[T]):
    """Returned from a resolver to ask the client; the framework runs the elicitation and injects the outcome."""

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
        wire_key: str,
    ) -> None:
        self.fn = fn
        self.params = params
        self.is_async = is_async
        # `T` from the `Elicit[T]` return arm; re-validates outcomes restored from `request_state`.
        self.elicit_schema = elicit_schema
        # Wire key for `input_requests`/`request_state`; assigned at registration so it
        # stays stable across rounds even when `module:qualname` collides (closures).
        self.wire_key = wire_key


def _type_hints(fn: Callable[..., Any]) -> dict[str, Any]:
    """Resolve type hints, falling back to `__call__` for callable instances (`get_type_hints` raises on them).

    Unresolvable hints yield an empty mapping: such callables simply have no resolved parameters.
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
    """Map parameters of `fn` annotated `Annotated[_, Resolve(...)]` to `(Resolve, wants_union)`.

    `wants_union` is True when the annotated type is an `ElicitationResult` member
    (the consumer wants the full outcome rather than the unwrapped model).
    """
    hints = _type_hints(fn)
    resolved: dict[str, tuple[Resolve, bool]] = {}
    for name in inspect.signature(fn).parameters:
        annotation = hints.get(name)
        if get_origin(annotation) is not Annotated:
            # Flag (rather than silently drop) a `Resolve` buried in a union, e.g. `Annotated[T, Resolve(f)] | None`.
            if _contains_resolve(annotation):
                raise InvalidSignature(
                    f"Parameter {name!r} of {_resolver_name(fn)!r} wraps `Resolve(...)` in a "
                    "union; annotate the parameter directly as `Annotated[T, Resolve(...)]`"
                )
            continue
        type_arg, *metadata = get_args(annotation)
        marker = next((m for m in metadata if isinstance(m, Resolve)), None)
        if marker is not None:
            resolved[name] = (marker, _wants_union(type_arg))
    return resolved


def _contains_resolve(annotation: Any) -> bool:
    if get_origin(annotation) is Annotated:
        return any(isinstance(m, Resolve) for m in get_args(annotation)[1:])
    return any(_contains_resolve(arg) for arg in get_args(annotation))


def _elicit_return_schema(return_annotation: Any, name: str) -> type[BaseModel] | None:
    """Extract `T` from a resolver return type's `Elicit[T]` arm, if present.

    Used to re-validate an outcome restored from `request_state` (a plain dict) into its model.

    Raises:
        InvalidSignature: If the annotation has more than one `Elicit[...]` arm.
    """
    candidates = get_args(return_annotation) if _is_union(return_annotation) else (return_annotation,)
    # Typing dedupes equal union members, so two arms here are genuinely distinct.
    arms = [c for c in candidates if get_origin(c) is Elicit]
    if len(arms) > 1:
        raise InvalidSignature(
            f"Resolver {name!r} return annotation has multiple Elicit arms; "
            "a resolver asks one question - split it into separate resolvers"
        )
    if not arms:
        return None
    schema = get_args(arms[0])[0]
    return schema if isinstance(schema, type) and issubclass(schema, BaseModel) else None


def _is_union(annotation: Any) -> bool:
    return get_origin(annotation) in (typing.Union, types.UnionType)


def _wants_union(type_arg: Any) -> bool:
    """True when `type_arg` is an `ElicitationResult` member (or a union of them).

    The `ElicitationResult` `TypeAliasType` carries its union on `__value__`: on
    `type_arg` itself when bare, on the origin when subscripted.
    """
    value = getattr(type_arg, "__value__", None) or getattr(get_origin(type_arg), "__value__", None)
    if value is not None:
        type_arg = value
    members = get_args(type_arg) if get_origin(type_arg) is not None else (type_arg,)
    return any(isinstance(m, type) and issubclass(m, _ELICITATION_RESULT_MEMBERS) for m in members)


def _resolver_key(fn: Callable[..., Any]) -> Hashable:
    """Identity key for memoizing a resolver.

    A bound method (pure-python or built-in) is recreated on each attribute access,
    so `id(fn)` differs every time; key it by its underlying function id (or, for
    built-ins, `__name__`) plus `__self__` identity. Everything else keys by `id`,
    so two distinct callables never collide even if they compare equal.
    """
    bound_self = getattr(fn, "__self__", None)
    if bound_self is not None:
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
        InvalidSignature: On a cyclic dependency, or a resolver parameter that is
            not a `Context`, a nested `Resolve`, or a tool argument by name.
    """
    plans: dict[Hashable, _ResolverPlan] = {}
    # Count how many distinct resolvers share each `module:qualname` base so closures
    # from one factory get distinct, deterministic wire keys (`base`, `base#1`, ...).
    base_counts: dict[str, int] = {}

    def analyze(fn: Callable[..., Any], stack: tuple[Hashable, ...]) -> None:
        key = _resolver_key(fn)
        if key in stack:
            raise InvalidSignature(f"Resolver {_resolver_name(fn)!r} has a cyclic dependency")
        if key in plans:
            return

        base = _state_key(fn)
        seen = base_counts.get(base, 0)
        base_counts[base] = seen + 1
        wire_key = base if seen == 0 else f"{base}#{seen}"

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

        elicit_schema = _elicit_return_schema(hints.get("return"), _resolver_name(fn))
        plans[key] = _ResolverPlan(fn, params, is_async_callable(fn), elicit_schema, wire_key)
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
    """Per-`tools/call` resolution state, shared across the DAG walk."""

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
        # `cache` dedups within the call by resolver identity. `persist` holds elicited
        # outcomes keyed by wire key - the next round's `request_state` - as the client's
        # validated wire data, never re-derived from a model, so encode-restore is the
        # identity. Pure resolvers are not persisted; they re-run each round.
        self.cache: dict[Hashable, ElicitationResult[Any]] = {}
        self.persist: dict[str, _StateEntry] = {}
        self.pending: InputRequests = {}


def _state_key(fn: Callable[..., Any]) -> str:
    """Worker-stable base wire key for a resolver: `module:qualname`, never `id(...)`.

    `input_requests`/`request_state` round-trip through the client and may resume on
    any worker (stateless HTTP). Resolvers sharing a base (bound methods, closures)
    are disambiguated deterministically by `build_resolver_plans`.
    """
    qualname = getattr(fn, "__qualname__", None) or type(fn).__qualname__
    module = getattr(fn, "__module__", None) or type(fn).__module__
    return f"{module}:{qualname}"


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

    Raises:
        ToolError: If an elicited value is declined or cancelled and the consumer
            asked for the unwrapped model (rather than the result union).
    """
    # `ctx.protocol_version` is None outside an active request (e.g. `MCPServer.call_tool()`
    # called directly); that maps to the synchronous transport, which never reaches a
    # server-to-client request anyway.
    res = _Resolution(plans, tool_args, context, _uses_input_required(context.protocol_version))
    injected: dict[str, Any] = {}
    for name, (marker, wants_union) in resolved_params.items():
        try:
            outcome = await _resolve(marker.fn, res)
        except _Pending:
            continue
        injected[name] = outcome if wants_union else _unwrap(outcome, name)

    if res.pending:
        return InputRequiredResult(input_requests=res.pending, request_state=_encode_state(res.persist))
    return injected


async def _resolve(fn: Callable[..., Any], res: _Resolution) -> ElicitationResult[Any]:
    """Resolve one resolver, deduped within the call by resolver identity.

    Raises `_Pending` when it (or a dependency) needs client input that has not arrived yet.
    """
    cache_key = _resolver_key(fn)
    if cache_key in res.cache:
        return res.cache[cache_key]

    plan = res.plans[cache_key]
    wire_key = plan.wire_key
    if wire_key in res.pending:
        # Already asked this round by another consumer.
        raise _Pending
    # Restore a prior outcome directly only when its model is known from the `Elicit[T]`
    # return arm; otherwise re-run the resolver so `_elicit` can re-validate the stored
    # answer against the live `Elicit.schema`.
    if wire_key in res.state and (plan.elicit_schema is not None or res.state[wire_key].action != "accept"):
        outcome = _restore_outcome(res, wire_key, plan.elicit_schema)
        if outcome is not None:
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
                # Keep visiting so all pending dependencies are batched into one round.
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
    else:
        # Plain outcomes are not persisted in `request_state`; the resolver re-runs next round.
        outcome = _accepted(result)

    res.cache[cache_key] = outcome
    return outcome


async def _elicit(elicit: Elicit[Any], key: str, res: _Resolution) -> ElicitationResult[Any]:
    """Turn a resolver's `Elicit` into an outcome via the negotiated transport."""
    if not res.input_required:
        return await res.context.elicit(elicit.message, elicit.schema)

    # A prior round's entry is re-validated against the live `Elicit.schema`; a recorded
    # outcome wins over a re-sent answer, and an invalid entry self-deletes, falling
    # through to the fresh answer (or to re-asking).
    outcome = _restore_outcome(res, key, elicit.schema)
    if outcome is not None:
        return outcome

    answer = res.answers.get(key)
    if answer is None:
        _require_form_elicitation(res.context, key)
        res.pending[key] = _elicit_request(elicit)
        raise _Pending
    if not isinstance(answer, ElicitResult):
        raise ToolError(f"Resolver {key!r} received a non-elicitation response")
    if answer.action == "accept":
        if answer.content is None:
            raise ToolError(f"Resolver {key!r} received an accepted elicitation with no content")
        try:
            data = elicit.schema.model_validate(answer.content)
        except ValidationError as e:
            raise ToolError(
                f"Resolver {key!r} received an accepted elicitation whose content does not match the requested schema"
            ) from e
        # Persist the wire content, never the model: next round revalidates the same bytes.
        res.persist[key] = _StateEntry(action="accept", data=answer.content)
        return AcceptedElicitation(data=data)
    if answer.action == "decline":
        res.persist[key] = _StateEntry(action="decline")
        return DeclinedElicitation()
    res.persist[key] = _StateEntry(action="cancel")
    return CancelledElicitation()


def _unwrap(outcome: ElicitationResult[Any], name: str) -> Any:
    if isinstance(outcome, AcceptedElicitation):
        return outcome.data
    raise ToolError(f"Resolver for parameter {name!r} could not resolve: elicitation was {outcome.action}")


def _is_elicit(value: Any) -> TypeGuard[Elicit[Any]]:
    return isinstance(value, Elicit)


def _accepted(data: Any) -> AcceptedElicitation[Any]:
    """Wrap a value as an accepted outcome without validation.

    Resolvers may return any type; restored `request_state` values are already validated.
    """
    return AcceptedElicitation[Any].model_construct(data=data)


def _uses_input_required(protocol_version: str | None) -> bool:
    """True when elicitation uses `InputRequiredResult` (>= 2026-07-28) rather than `elicitation/create`."""
    return protocol_version is not None and is_version_at_least(protocol_version, _INPUT_REQUIRED_VERSION)


def _require_form_elicitation(context: Context[Any, Any], key: str) -> None:
    """Assert the client declared form elicitation before queueing a question for it.

    The spec forbids `input_requests` entries the client lacks a capability for. A bare
    `elicitation: {}` (the only shape before modes existed) counts as form support; an
    explicit url-only declaration does not.

    Raises:
        MCPError: `MISSING_REQUIRED_CLIENT_CAPABILITY` with a `requiredCapabilities` payload.
    """
    capabilities = context.client_capabilities
    elicitation = capabilities.elicitation if capabilities is not None else None
    if elicitation is not None and (elicitation.form is not None or elicitation.url is None):
        return
    data = MissingRequiredClientCapabilityErrorData(
        required_capabilities=ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability()))
    )
    raise MCPError(
        code=MISSING_REQUIRED_CLIENT_CAPABILITY,
        message=f"Client did not declare the form elicitation capability required by resolver {key!r}",
        data=data.model_dump(by_alias=True, mode="json", exclude_none=True),
    )


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
    """Decode per-call progress from client-trusted `request_state` (integrity sealing is a follow-up).

    Anything malformed reads as "no progress yet".
    """
    if not request_state:
        return {}
    try:
        state = _State.model_validate_json(request_state)
    except ValidationError:
        return {}
    return state.outcomes if state.v == _STATE_VERSION else {}


def _encode_state(outcomes: Mapping[str, _StateEntry]) -> str:
    """Encode recorded elicitation outcomes (keyed by wire key) for the next round."""
    return _State(v=_STATE_VERSION, outcomes=dict(outcomes)).model_dump_json()


def _outcome_from_state(entry: _StateEntry, schema: type[BaseModel] | None) -> ElicitationResult[Any]:
    """Rebuild an `ElicitationResult` from a decoded `request_state` entry.

    Raises:
        ValidationError: If `schema` is known and the entry's data does not validate.
    """
    if entry.action == "decline":
        return DeclinedElicitation()
    if entry.action == "cancel":
        return CancelledElicitation()
    data = entry.data
    if schema is not None:
        data = schema.model_validate(data)
    return _accepted(data)


def _restore_outcome(res: _Resolution, key: str, schema: type[BaseModel] | None) -> ElicitationResult[Any] | None:
    """Restore `key`'s recorded outcome from a prior round, or `None` when absent.

    Client-trusted state: an entry whose data fails validation is dropped as if no
    progress was recorded, so the question is asked again. The original entry is
    carried forward unchanged into `res.persist` - the next round's `request_state`
    is built from it, so an earlier answer must stay there or it would be re-asked.
    """
    entry = res.state.get(key)
    if entry is None:
        return None
    try:
        outcome = _outcome_from_state(entry, schema)
    except ValidationError:
        del res.state[key]
        return None
    res.persist[key] = entry
    return outcome


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
