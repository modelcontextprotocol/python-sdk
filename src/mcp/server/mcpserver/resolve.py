"""Resolver dependency injection for MCPServer tools.

A tool parameter annotated `Annotated[T, Resolve(fn)]` is filled by running the
resolver `fn` before the tool body, instead of from the LLM-supplied arguments.
Resolvers form a DAG: a resolver may declare its own `Resolve(...)` dependencies,
take tool arguments by name, and take the `Context`. A resolver may return a
request marker - `Elicit[T]` to ask the user, `Sample` to run an LLM call on the
client, or `ListRoots` to fetch the client's roots - and the framework runs the
request and injects the response. These are the three request kinds the
multi-round-trip flow allows.

The framework picks the transport from the negotiated protocol. At >= 2026-07-28
it returns an `InputRequiredResult` carrying the batched requests and resumes
when the client retries with `input_responses`/`request_state` (independent
resolvers are asked in one round; a resolver depending on another's answer is
asked in a later round). At <= 2025-11-25 it issues the standalone server-to-client
request (`elicitation/create`, `sampling/createMessage`, `roots/list`) mid-call.
Only *asked* outcomes are carried in `request_state` across rounds (so the user
is asked - and the client's LLM is sampled - once per question). Resolver
bodies may re-run on every round; a recorded outcome is consulted only when the
body asks its question again, so a resolver's own computation always wins over
anything the client echoes back in `request_state`.

Whether the consumer receives the unwrapped model or the full
`ElicitationResult` union is decided by the consumer's annotation:

- `Annotated[T, Resolve(fn)]` -> unwrapped `T`; decline/cancel aborts the call.
- `Annotated[ElicitationResult[T], Resolve(fn)]` (or a specific member) -> the
  full outcome; the consumer branches on accept/decline/cancel.

`Sample` and `ListRoots` have no decline arm (a client refuses by erroring), so
their consumers annotate the result directly: `CreateMessageResult` (or
`CreateMessageResultWithTools` when tools are given) and `ListRootsResult`.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import logging
import types
import typing
from collections.abc import Callable, Hashable, Mapping
from typing import Annotated, Any, Generic, Literal, TypeGuard, get_args, get_origin

import anyio.to_thread
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ElicitationCapability,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    FormElicitationCapability,
    IncludeContext,
    InputRequest,
    InputRequests,
    InputRequiredResult,
    InputResponses,
    ListRootsRequest,
    ListRootsResult,
    MissingRequiredClientCapabilityErrorData,
    ModelPreferences,
    RootsCapability,
    SamplingCapability,
    SamplingMessage,
    SamplingToolsCapability,
    Tool,
    ToolChoice,
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
from mcp.server.request_state import compact_json
from mcp.server.validation import validate_tool_use_result_messages
from mcp.shared._callable_inspection import is_async_callable
from mcp.shared.exceptions import MCPError
from mcp.shared.message import ServerMessageMetadata

T = TypeVar("T", bound=BaseModel)

# The union members the framework injects when a consumer opts into the outcome.
_ELICITATION_RESULT_MEMBERS = (AcceptedElicitation, DeclinedElicitation, CancelledElicitation)

# First protocol revision whose `tools/call` carries elicitation inside
# `InputRequiredResult` rather than as a standalone server-to-client request.
# Pinned (not `LATEST_MODERN_VERSION`, which moves when newer revisions are added).
_INPUT_REQUIRED_VERSION = "2026-07-28"
_STATE_VERSION = 3  # v3: recorded and pended outcomes pinned to ASCII-canonical question renders

logger = logging.getLogger(__name__)


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


class Sample:
    """A resolver's request to sample the client's LLM.

    Returned from a resolver to have the client run an LLM call; the framework
    injects the `CreateMessageResult` (a `CreateMessageResultWithTools` when
    `tools` are given). Requires the client to declare the `sampling` capability
    (plus `sampling.tools` when tools are given). Mirrors the parameters of
    `sampling/createMessage`.

    On >= 2026-07-28 the rendered request must be identical across retry rounds
    (the recorded result is pinned to it) - derive it only from tool arguments
    and stable data, never timestamps or random values. The sampled result rides
    the `request_state` envelope on every remaining round, so very large
    completions inflate the rest of the exchange.

    Note: `include_context` values other than "none" are deprecated in the draft
    specification and should be avoided.
    """

    def __init__(
        self,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
        tools: list[Tool] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> None:
        validate_tool_use_result_messages(messages)
        self.params = CreateMessageRequestParams(
            messages=messages,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            include_context=include_context,
            temperature=temperature,
            stop_sequences=stop_sequences,
            metadata=metadata,
            model_preferences=model_preferences,
            tools=tools,
            tool_choice=tool_choice,
        )


class ListRoots:
    """A resolver's request for the client's current roots.

    Returned from a resolver to fetch the client's roots list; the framework
    injects the `ListRootsResult`. Requires the client to declare the `roots`
    capability.
    """


_Marker = Elicit[Any] | Sample | ListRoots
"""The request kinds a resolver may return - the closed set the multi-round-trip flow allows."""


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
        wire_key: str,
    ) -> None:
        self.fn = fn
        self.params = params
        self.is_async = is_async
        # Deterministic, collision-free key for this resolver's elicitation on the
        # wire (`input_requests`/`request_state`). Assigned at registration so it is
        # stable across rounds even when `module:qualname` collides (closures).
        self.wire_key = wire_key


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
            # A `Resolve` marker is only honored at the top level; flag (rather than
            # silently drop) one buried in a union, e.g. `Annotated[T, Resolve(f)] | None`.
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


def returns_input_required(fn: Callable[..., Any]) -> bool:
    """True when `fn`'s return annotation carries an `InputRequiredResult` arm.

    Used at tool registration to reject combining `Resolve(...)` parameters with a
    hand-rolled `InputRequiredResult` flow: a call has a single
    `input_responses`/`request_state` channel, so the two flows would overwrite
    each other's state and the call could never converge.
    """
    return _has_input_required_arm(_type_hints(fn).get("return"))


def _has_input_required_arm(annotation: Any) -> bool:
    """Walk an annotation's arms through `Annotated`, type aliases, and unions."""
    if get_origin(annotation) is Annotated:
        return _has_input_required_arm(get_args(annotation)[0])
    # A `type X = ...` / `TypeAliasType` alias carries its target on `__value__` (a
    # subscripted alias forwards the attribute to its origin). The access evaluates
    # a PEP 695 alias lazily, so an alias naming things unavailable at runtime
    # (TYPE_CHECKING-only imports) raises NameError; such an alias declares no arm
    # this check can see, and the in-call guard in `Tool.run` still covers it.
    try:
        value = getattr(annotation, "__value__", None)
    except NameError:
        return False
    if value is not None:
        return _has_input_required_arm(value)
    if _is_union(annotation):
        return any(_has_input_required_arm(arg) for arg in get_args(annotation))
    return isinstance(annotation, type) and issubclass(annotation, InputRequiredResult)


def _contains_resolve(annotation: Any) -> bool:
    """True when a `Resolve` marker is nested inside `annotation` (e.g. a union member)."""
    if get_origin(annotation) is Annotated:
        return any(isinstance(m, Resolve) for m in get_args(annotation)[1:])
    return any(_contains_resolve(arg) for arg in get_args(annotation))


def _check_elicit_return(return_annotation: Any, name: str) -> None:
    """Validate the request-marker arms of a resolver's return annotation.

    Raises:
        InvalidSignature: If the annotation has more than one marker arm
            (`Elicit[...]`, `Sample`, `ListRoots`); a resolver asks one
            question - a second arm means it should be split.
    """
    # A bare marker type is itself a candidate; a union contributes its members.
    candidates = get_args(return_annotation) if _is_union(return_annotation) else (return_annotation,)
    # Typing dedupes equal union members, so two arms here are genuinely distinct.
    arms: list[Any] = [
        c
        for c in candidates
        # The `get_origin(c) is None` guard keeps 3.10 safe: there `dict[str, Any]`
        # passes `isinstance(c, type)` and would crash `issubclass`.
        if get_origin(c) is Elicit
        or (get_origin(c) is None and isinstance(c, type) and issubclass(c, Elicit | Sample | ListRoots))
    ]
    if len(arms) > 1:
        raise InvalidSignature(
            f"Resolver {name!r} return annotation has multiple Elicit/Sample/ListRoots arms; "
            "a resolver asks one question - split it into separate resolvers"
        )


def _is_union(annotation: Any) -> bool:
    return get_origin(annotation) in (typing.Union, types.UnionType)


def _wants_union(type_arg: Any) -> bool:
    """True when `type_arg` is an `ElicitationResult` member (or a union of them).

    Handles the subscripted `ElicitationResult[T]` alias (a `TypeAliasType` whose
    union is on the origin's `__value__`), the bare `ElicitationResult` alias (the
    `__value__` is on `type_arg` itself), an explicit `AcceptedElicitation[T] | ...`
    union, and a single member.
    """
    # Unwrap the `ElicitationResult` alias whether it is bare or subscripted.
    value = getattr(type_arg, "__value__", None) or getattr(get_origin(type_arg), "__value__", None)
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

        _check_elicit_return(hints.get("return"), _resolver_name(fn))
        plans[key] = _ResolverPlan(fn, params, is_async_callable(fn), wire_key)
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

    `input_required` selects the transport: at >= 2026-07-28 requests are
    batched into `pending` and surfaced as an `InputRequiredResult`; at older
    revisions each marker is answered synchronously over the back-channel.
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
        decoded = _decode_state(context.request_state if input_required else None)
        self.state = decoded.outcomes
        # Digests of the questions asked last round: an answer is accepted only
        # for the exact rendering the client was shown.
        self.asked = decoded.asked
        # In-call dedup keyed by resolver identity (distinguishes two instances of
        # the same bound method); `persist` holds the wire-shaped record of each
        # elicited outcome, keyed by its wire key - exactly what the next round's
        # `request_state` carries. Entries are the client's own (validated) wire
        # data, never re-derived from a model, so encode-restore is the identity.
        # Pure resolvers are cheap to re-run each round and are not persisted.
        self.cache: dict[Hashable, ElicitationResult[Any]] = {}
        self.persist: dict[str, _StateEntry] = {}
        self.pending: InputRequests = {}


def _state_key(fn: Callable[..., Any]) -> str:
    """Worker-stable base wire key for a resolver, derived only from registration data.

    `input_requests`/`request_state` must round-trip through the client and resume on
    any worker (stateless HTTP), so the key carries no `id(...)`: it is the resolver's
    `module:qualname` (a callable object uses its type's). Distinct resolvers that
    share this base - two instances of one method, two closures from one factory - are
    disambiguated deterministically by `build_resolver_plans` (`base`, `base#1`, ...).
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

    Each question is asked once - its answer is carried in `request_state` across
    rounds and satisfies the question when the resolver asks it again. Resolver
    bodies themselves may re-run on each round; a recorded answer is consulted
    only when the body asks, never in place of running it.

    Raises:
        ToolError: If an elicited value is declined or cancelled and the consumer
            asked for the unwrapped model (rather than the result union).
    """
    # `ctx.protocol_version` is `None` outside an active request: `MCPServer.call_tool()`
    # called directly builds such a `Context`, and a tool whose resolvers never elicit
    # must still work there. A missing version means the synchronous (non-input_required)
    # transport, which never reaches a server-to-client request anyway.
    res = _Resolution(plans, tool_args, context, _uses_input_required(context.protocol_version))
    injected: dict[str, Any] = {}
    for name, (marker, wants_union) in resolved_params.items():
        try:
            outcome = await _resolve(marker.fn, res)
        except _Pending:
            continue
        injected[name] = outcome if wants_union else _unwrap(outcome, name)

    if res.pending:
        asked = {key: _request_digest(request) for key, request in res.pending.items()}
        return InputRequiredResult(input_requests=res.pending, request_state=_encode_state(res.persist, asked))
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
    wire_key = plan.wire_key
    if wire_key in res.pending:
        # Already asked this round by another consumer; don't run the resolver again.
        raise _Pending

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

    if _is_marker(result):
        outcome = await _fulfil(result, wire_key, res)
    else:
        # A resolver may return any type (not just `BaseModel`), so accept it as the
        # outcome without validating against the schema bound. Plain outcomes are not
        # persisted in `request_state`; the resolver re-runs next round instead.
        outcome = _accepted(result)

    res.cache[cache_key] = outcome
    return outcome


async def _fulfil(marker: _Marker, key: str, res: _Resolution) -> ElicitationResult[Any]:
    """Turn a resolver's request marker into an outcome via the negotiated transport."""
    if not res.input_required:
        # Gate only when the handshake's declaration is visible. A session with no
        # client info (e.g. stateless HTTP) has no back-channel either, and the send
        # path reports that truthfully; on >= 2026-07-28 absence means not declared,
        # because capabilities arrive per-request there.
        if res.context.client_capabilities is not None:
            _require_capability(res.context, marker, key)
        if isinstance(marker, Elicit):
            return await res.context.elicit(marker.message, marker.schema)
        result = await res.context.session.send_request(
            _render_request(marker),
            _result_type(marker),
            metadata=ServerMessageMetadata(related_request_id=res.context.request_id),
        )
        return _accepted(result)

    request = _render_request(marker)
    q = _request_digest(request)

    # A recorded outcome from a prior round is consulted only here, after the body
    # decided to ask, so a `request_state` entry can never stand in for a resolver's
    # own computation. A recorded outcome wins over a re-sent answer.
    outcome = _restore_outcome(res, key, marker, q)
    if outcome is not None:
        return outcome

    answer = res.answers.get(key)
    # An answer counts only for the rendering recorded when it was asked; an answer to
    # an unrecorded or differently-worded question re-asks instead of being consumed.
    if answer is not None and res.asked.get(key) != q:
        logger.info("Discarding the answer for resolver %r: the question changed since it was asked", key)
        answer = None
    if answer is None:
        _require_capability(res.context, marker, key)
        res.pending[key] = request
        raise _Pending
    if not isinstance(marker, Elicit):
        # The response union cannot always discriminate the two sampling result shapes
        # (a no-tool-use answer to a tools request parses as the plain one), so validate
        # the wire data against the marker's expected model instead of the union member.
        wire = answer.model_dump(mode="json", by_alias=True, exclude_none=True)
        try:
            result = _result_type(marker).model_validate(wire)
        except ValidationError as e:
            raise ToolError(f"Resolver {key!r} received a response of the wrong kind") from e
        res.persist[key] = _StateEntry(action="accept", data=wire, q=q)
        return _accepted(result)
    if not isinstance(answer, ElicitResult):
        raise ToolError(f"Resolver {key!r} received a non-elicitation response")
    if answer.action == "accept":
        if answer.content is None:
            raise ToolError(f"Resolver {key!r} received an accepted elicitation with no content")
        try:
            data = marker.schema.model_validate(answer.content)
        except ValidationError as e:
            raise ToolError(
                f"Resolver {key!r} received an accepted elicitation whose content does not match the requested schema"
            ) from e
        # Persist the exact wire content that just passed validation - never the
        # model - so restoring next round revalidates the same bytes the client sent.
        res.persist[key] = _StateEntry(action="accept", data=answer.content, q=q)
        return AcceptedElicitation(data=data)
    if answer.action == "decline":
        res.persist[key] = _StateEntry(action="decline", q=q)
        return DeclinedElicitation()
    res.persist[key] = _StateEntry(action="cancel", q=q)
    return CancelledElicitation()


def _unwrap(outcome: ElicitationResult[Any], name: str) -> Any:
    if isinstance(outcome, AcceptedElicitation):
        return outcome.data
    raise ToolError(f"Resolver for parameter {name!r} could not resolve: elicitation was {outcome.action}")


def _is_marker(value: Any) -> TypeGuard[_Marker]:
    """Runtime narrow of a resolver's return value to a request marker."""
    return isinstance(value, Elicit | Sample | ListRoots)


def _accepted(data: Any) -> AcceptedElicitation[Any]:
    """Wrap a resolved value as an accepted outcome without schema validation.

    A resolver may return any type (the schema bound only constrains `Elicit[T]`),
    and a value restored from `request_state` is already validated.
    """
    return AcceptedElicitation[Any].model_construct(data=data)


def _uses_input_required(protocol_version: str | None) -> bool:
    """True when this request must elicit via `InputRequiredResult` (>= 2026-07-28).

    Older revisions still carry a standalone `elicitation/create` server-to-client
    request, so the framework keeps the synchronous `ctx.elicit()` path for them.
    """
    return protocol_version is not None and is_version_at_least(protocol_version, _INPUT_REQUIRED_VERSION)


def _require_capability(context: Context[Any, Any], marker: _Marker, key: str) -> None:
    """Assert the client declared the capability `marker`'s request needs before sending it.

    The spec forbids sending a client a request it has not declared a capability
    for; the same predicate gates both transports. A bare `elicitation: {}`
    declaration (the only shape before modes existed) counts as form support; an
    explicit url-only declaration does not.

    Raises:
        MCPError: With code `MISSING_REQUIRED_CLIENT_CAPABILITY` and a
            `requiredCapabilities` payload when the capability is not declared.
    """
    capabilities = context.client_capabilities
    if isinstance(marker, Elicit):
        elicitation = capabilities.elicitation if capabilities is not None else None
        if elicitation is not None and (elicitation.form is not None or elicitation.url is None):
            return
        required = ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability()))
        name = "form elicitation"
    elif isinstance(marker, Sample):
        sampling = capabilities.sampling if capabilities is not None else None
        wants_tools = marker.params.tools is not None or marker.params.tool_choice is not None
        if sampling is not None and (not wants_tools or sampling.tools is not None):
            return
        required = ClientCapabilities(
            sampling=SamplingCapability(tools=SamplingToolsCapability() if wants_tools else None)
        )
        name = "sampling.tools" if wants_tools else "sampling"
    else:
        if capabilities is not None and capabilities.roots is not None:
            return
        required = ClientCapabilities(roots=RootsCapability())
        name = "roots"
    data = MissingRequiredClientCapabilityErrorData(required_capabilities=required)
    raise MCPError(
        code=MISSING_REQUIRED_CLIENT_CAPABILITY,
        message=f"Client did not declare the {name} capability required by resolver {key!r}",
        data=data.model_dump(by_alias=True, mode="json", exclude_none=True),
    )


def _render_request(marker: _Marker) -> InputRequest:
    """Render a marker as its wire request - the same shape on both transports."""
    if isinstance(marker, Elicit):
        json_schema = render_elicitation_schema(marker.schema)
        return ElicitRequest(params=ElicitRequestFormParams(message=marker.message, requested_schema=json_schema))
    if isinstance(marker, Sample):
        return CreateMessageRequest(params=marker.params)
    return ListRootsRequest()


def _result_type(
    marker: Sample | ListRoots,
) -> type[CreateMessageResult] | type[CreateMessageResultWithTools] | type[ListRootsResult]:
    """The result model a `Sample`/`ListRoots` response must validate against."""
    if isinstance(marker, ListRoots):
        return ListRootsResult
    return CreateMessageResult if marker.params.tools is None else CreateMessageResultWithTools


class _StateEntry(BaseModel):
    """One resolver's recorded outcome inside `request_state`."""

    action: Literal["accept", "decline", "cancel"]
    data: Any = None
    q: str | None = None
    """Digest of the exact rendered question this outcome answered."""


def _request_digest(request: InputRequest) -> str:
    """Pin an outcome to the exact rendered question the client was shown.

    A redeploy that rewords or reshapes a question re-asks it instead of reusing the recorded answer.
    """
    params = request.params
    rendered = compact_json(params.model_dump(mode="json", by_alias=True, exclude_none=True) if params else None)
    digest = hashlib.sha256(rendered.encode()).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class _State(BaseModel):
    """The decoded `request_state`: resolver progress from earlier rounds."""

    v: int
    outcomes: dict[str, _StateEntry] = {}
    asked: dict[str, str] = {}
    """Question digest of each elicitation asked last round, keyed by wire key."""


def _decode_state(request_state: str | None) -> _State:
    """Decode the per-call resolution progress from `request_state`.

    Parsed with stdlib `json.loads` because `_encode_state` may emit escaped
    lone surrogates, which pydantic's JSON parser rejects. The string arrives
    boundary-authenticated, so malformed content or a version mismatch is
    drift within the operator's own fleet (e.g. a rolling upgrade) and is
    treated as "no progress yet".
    """
    empty = _State(v=_STATE_VERSION)
    if not request_state:
        return empty
    try:
        state = _State.model_validate(json.loads(request_state))
    except ValueError:
        return empty
    return state if state.v == _STATE_VERSION else empty


def _encode_state(outcomes: Mapping[str, _StateEntry], asked: Mapping[str, str]) -> str:
    """Encode recorded outcomes and asked-question digests for the next round.

    Outcome entries already hold the client's wire-shaped data exactly as it was
    sent (and validated), so encoding is pure wrapping: encode-restore is the
    identity.
    """
    state = _State(v=_STATE_VERSION, outcomes=dict(outcomes), asked=dict(asked))
    return compact_json(state.model_dump(mode="json"))


def _outcome_from_state(entry: _StateEntry, marker: _Marker) -> ElicitationResult[Any]:
    """Rebuild an outcome from a decoded `request_state` entry.

    Raises:
        ValidationError: If the entry does not fit the live marker - accepted
            data failing the expected shape, or a decline/cancel recorded for a
            kind that has no such outcome (its `data` is `None`).
    """
    if isinstance(marker, Elicit):
        if entry.action == "decline":
            return DeclinedElicitation()
        if entry.action == "cancel":
            return CancelledElicitation()
        return _accepted(marker.schema.model_validate(entry.data))
    return _accepted(_result_type(marker).model_validate(entry.data))


def _restore_outcome(res: _Resolution, key: str, marker: _Marker, q: str) -> ElicitationResult[Any] | None:
    """Restore `key`'s recorded outcome from a prior round, or `None` when absent.

    An entry pinned to a question digest other than `q`, or whose accepted
    data fails validation against the live `schema`, is dropped as if no
    progress was recorded, so the question is asked again.

    Carries the original decoded entry forward unchanged in `res.persist`: if a
    later resolver is still pending, the next round's `request_state` is built from
    `res.persist`, so an earlier answer must stay there - byte-identical, never
    re-derived - or it would be dropped and re-asked.
    """
    entry = res.state.get(key)
    if entry is None:
        return None
    if entry.q != q:
        del res.state[key]
        return None
    try:
        outcome = _outcome_from_state(entry, marker)
    except ValidationError:
        del res.state[key]
        return None
    res.persist[key] = entry
    return outcome


__all__ = [
    "Resolve",
    "Elicit",
    "Sample",
    "ListRoots",
    "ElicitationResult",
    "AcceptedElicitation",
    "DeclinedElicitation",
    "CancelledElicitation",
    "find_resolved_parameters",
    "build_resolver_plans",
    "resolve_arguments",
    "returns_input_required",
]
