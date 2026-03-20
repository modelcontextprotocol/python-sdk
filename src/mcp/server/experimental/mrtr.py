"""MRTR (SEP-2322) server-side primitives — footgun-prevention layers.

!!! warning
    These APIs are experimental and may change or be removed without notice.

The naive MRTR handler is de-facto GOTO: re-entry jumps to the top, state
progression is implicit in ``input_responses`` checks, and side-effects
above the guard execute on every retry. Two primitives here make safe code
the easy path:

- :class:`MrtrCtx` — ``ctx.once(key, fn)`` idempotency guard. Opt-in per
  call site; unwrapped mutations still fire twice. Makes the hazard
  *visually distinct* from safe code, which is reviewable. Lightweight —
  use for single-question tools with one side-effect.

- :class:`ToolBuilder` — structural decomposition into named steps.
  ``end_step`` runs exactly once, structurally unreachable until every
  ``incomplete_step`` has returned data. No "above the guard" zone to get
  wrong. Boilerplate pays for itself at 3+ rounds.

Both track progress in ``request_state`` (base64-JSON here; a production
SDK MUST HMAC-sign the blob — see the note on :func:`_encode_state`).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar, cast

from mcp.types import CallToolRequestParams, CallToolResult, IncompleteResult, InputRequests

__all__ = ["MrtrCtx", "ToolBuilder", "input_response", "sse_retry_shim", "dispatch_by_version"]

ArgsT = TypeVar("ArgsT")


# ─── requestState encode/decode ──────────────────────────────────────────────
#
# DEMO ONLY: plain base64-JSON. A production SDK MUST HMAC-sign this blob
# because the client can otherwise forge step-done / once-executed markers
# and skip the guards entirely. A per-session key derived from the initialize
# handshake keeps it stateless. Without signing, the safety story here is
# advisory, not enforced.


def _encode_state(state: Any) -> str:
    return base64.b64encode(json.dumps(state).encode()).decode()


def _decode_state(blob: str | None) -> dict[str, Any]:
    if not blob:
        return {}
    try:
        result = json.loads(base64.b64decode(blob))
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}
    except (ValueError, json.JSONDecodeError):  # pragma: no cover
        return {}


def input_response(params: CallToolRequestParams, key: str) -> dict[str, Any] | None:
    """Pull an accepted elicitation's content out of ``params.input_responses``.

    Returns ``None`` if the key is absent, declined, or cancelled. Sugar for
    the common guard-first pattern::

        units = input_response(params, "units")
        if units is None:
            return IncompleteResult(input_requests={"units": ...})
    """
    if not params.input_responses:
        return None
    entry = params.input_responses.get(key)
    if not entry:
        return None
    if entry.get("action") != "accept":
        return None
    return entry.get("content")


# ─── Option F: MrtrCtx.once — idempotency guard ──────────────────────────────


class MrtrCtx:
    """MRTR context with a ``once`` guard tracked in ``request_state``.

    Handler stays monolithic (guard-first, like a raw MRTR handler), but
    side-effects can be wrapped for at-most-once execution across retries::

        ctx = MrtrCtx(params)
        ctx.once("audit", lambda: audit_log(params.arguments["x"]))

        units = input_response(params, "units")
        if units is None:
            return ctx.incomplete({"units": ElicitRequest(...)})

        return CallToolResult(...)

    Opt-in: an unwrapped mutation still fires twice. The footgun isn't
    eliminated — it's made visually distinct from safe code, which is
    reviewable. A bare ``db.write()`` above the guard is the red flag;
    ``ctx.once("write", lambda: db.write())`` reads as "I considered
    re-entry."

    Crash window: if the server dies between ``fn()`` completing and
    ``request_state`` reaching the client, the next invocation re-executes.
    At-most-once under normal operation, not crash-safe. For financial
    operations use external idempotency (request ID as DB unique key).
    """

    def __init__(self, params: CallToolRequestParams) -> None:
        self._params = params
        prior = _decode_state(params.request_state)
        self._executed: set[str] = set(prior.get("executed", []))

    @property
    def input_responses(self) -> dict[str, Any] | None:  # pragma: no cover
        return self._params.input_responses

    def once(self, key: str, fn: Callable[[], Any]) -> None:
        """Run ``fn`` at most once across all MRTR rounds for this tool call.

        On subsequent rounds where ``key`` is marked executed in
        ``request_state``, ``fn`` is skipped entirely.
        """
        if key in self._executed:
            return
        fn()
        self._executed.add(key)

    def has_run(self, key: str) -> bool:
        """Check if ``once(key, ...)`` has fired on a prior round."""
        return key in self._executed

    def incomplete(self, input_requests: InputRequests) -> IncompleteResult:
        """Build an IncompleteResult that carries the executed-keys set.

        Call this instead of constructing ``IncompleteResult`` directly so
        the ``once`` guard holds across retry. Without this, ``once`` is a
        no-op on the next round.
        """
        return IncompleteResult(
            input_requests=input_requests,
            request_state=_encode_state({"executed": sorted(self._executed)}),
        )


# ─── Option G: ToolBuilder — structural step decomposition ───────────────────


IncompleteStep = Callable[[ArgsT, dict[str, Any]], IncompleteResult | dict[str, Any]]
"""An incomplete-step function. Receives args + all input responses collected
so far. Returns either an :class:`IncompleteResult` (needs more input) or a
dict to merge into the collected data passed to the next step.

MUST be idempotent — it can re-run if the client tampers with ``request_state``
(unsigned in this draft) or if a step before it wasn't the most-recently
completed. Side-effects belong in the end step.
"""

EndStep = Callable[[ArgsT, dict[str, Any]], CallToolResult]
"""The end-step function. Receives args + the merged data from all prior
steps. Runs exactly once, when every incomplete step has returned data.
This is the safe zone — put side-effects here.
"""


class ToolBuilder(Generic[ArgsT]):
    """Explicit step decomposition for MRTR handlers.

    The monolithic handler becomes a sequence of named step functions.
    ``end_step`` is structurally unreachable until every ``incomplete_step``
    has returned data — the SDK's step-tracking (via ``request_state``) is
    the guard, not developer discipline::

        def ask_units(args, inputs):
            u = inputs.get("units")
            if not u or u.get("action") != "accept":
                return IncompleteResult(input_requests={"units": ElicitRequest(...)})
            return {"units": u["content"]["u"]}

        def fetch_weather(args, collected):
            audit_log(args)              # runs exactly once
            return CallToolResult(...)   # uses collected["units"]

        handler = (
            ToolBuilder[dict[str, str]]()
            .incomplete_step("ask_units", ask_units)
            .end_step(fetch_weather)
            .build()
        )

        server = Server("demo", on_call_tool=handler)

    Steps are named (not ordinal) so reordering during development doesn't
    silently remap data. Each name must be unique; ``build()`` raises on
    duplicates.

    Boilerplate vs a raw guard-first handler: two function defs + ``.build()``
    to replace a 3-line ``if not x: return IncompleteResult(...)``. Worth it at
    3+ rounds or when the side-effect story matters. Overkill for a single
    question — use :class:`MrtrCtx` instead.
    """

    def __init__(self) -> None:
        self._steps: list[tuple[str, IncompleteStep[ArgsT]]] = []
        self._end: EndStep[ArgsT] | None = None

    def incomplete_step(self, name: str, fn: IncompleteStep[ArgsT]) -> ToolBuilder[ArgsT]:
        """Append a step that may return IncompleteResult or data to collect."""
        self._steps.append((name, fn))
        return self

    def end_step(self, fn: EndStep[ArgsT]) -> ToolBuilder[ArgsT]:
        """Set the final step that runs exactly once with all collected data."""
        self._end = fn
        return self

    def build(self) -> Callable[[Any, CallToolRequestParams], Awaitable[CallToolResult | IncompleteResult]]:
        """Produce a lowlevel ``on_call_tool`` handler."""
        if self._end is None:
            raise ValueError("ToolBuilder: end_step is required")
        names = [n for n, _ in self._steps]
        if len(names) != len(set(names)):
            raise ValueError(f"ToolBuilder: duplicate step names in {names}")

        steps = list(self._steps)
        end = self._end

        async def handler(ctx: Any, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
            args: ArgsT = params.arguments  # type: ignore[assignment]
            prior = _decode_state(params.request_state)
            done: set[str] = set(prior.get("done", []))
            inputs = params.input_responses or {}
            collected: dict[str, Any] = dict(prior.get("collected", {}))

            for name, step in steps:
                if name in done:
                    continue
                result = step(args, inputs)
                if isinstance(result, IncompleteResult):
                    return IncompleteResult(
                        input_requests=result.input_requests,
                        request_state=_encode_state({"done": sorted(done), "collected": collected}),
                    )
                collected.update(result)
                done.add(name)

            return end(args, collected)

        return handler


# ─── Option A: SSE retry shim (comparison artifact, not a ship target) ───────


MrtrHandler = Callable[[Any, CallToolRequestParams], Awaitable[CallToolResult | IncompleteResult]]
"""Signature of an MRTR-native lowlevel handler."""


def sse_retry_shim(mrtr_handler: MrtrHandler, *, max_rounds: int = 8) -> MrtrHandler:  # pragma: no cover
    """Wrap an MRTR-native handler so pre-MRTR clients also get elicitation.

    When the negotiated version is pre-MRTR and the handler returns
    ``IncompleteResult``, this shim drives the retry loop *locally* — it
    fulfils each ``InputRequest`` via real SSE (``ctx.session.elicit_form()``),
    collects the answers, and re-invokes the handler with ``input_responses``
    populated. Repeat until complete.

    This only works on infra that can actually hold SSE — the elicit call is
    a real SSE round-trip. On a horizontally-scaled MRTR-only deployment (the
    whole reason to adopt MRTR), this fails at runtime when an old client
    connects. That constraint lives nowhere near the tool code. If that's the
    deployment, use Option E (degrade) instead — it's the SDK default.

    Hidden cost: the handler is silently re-invoked. The MRTR shape makes
    re-entry safe by construction (the guard is visible in source), but the
    *loop* is invisible. If the handler does something expensive before the
    guard, you won't find out until an old client connects in prod.

    Comparison artifact — not tested against a pre-MRTR client in this draft
    because the SDK's LATEST_PROTOCOL_VERSION is still 2025-11-25. Covered
    by E2E tests once the version bumps.
    """
    from mcp.types import ElicitRequest, ElicitRequestFormParams

    async def wrapped(ctx: Any, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
        version = ctx.session.client_params.protocol_version if ctx.session.client_params else None
        # Fast path: new client — pass through.
        if version is None or str(version) >= "2026-06-01":
            return await mrtr_handler(ctx, params)

        # Old client: drive the retry loop locally over SSE.
        responses: dict[str, Any] = dict(params.input_responses or {})
        state = params.request_state

        for _round in range(max_rounds):
            retry = params.model_copy(update={"input_responses": responses or None, "request_state": state})
            result = await mrtr_handler(ctx, retry)

            if isinstance(result, CallToolResult):
                return result

            state = result.request_state

            if not result.input_requests:
                return CallToolResult(
                    content=[{"type": "text", "text": "IncompleteResult with no inputRequests on pre-MRTR session."}],  # type: ignore[list-item]
                    is_error=True,
                )

            for key, req in result.input_requests.items():
                if not isinstance(req, ElicitRequest) or not isinstance(req.params, ElicitRequestFormParams):
                    continue
                elicit_result = await ctx.session.elicit_form(
                    message=req.params.message,
                    requested_schema=req.params.requested_schema,
                    related_request_id=ctx.request_id,
                )
                responses[key] = elicit_result.model_dump(by_alias=True, exclude_none=True)

        return CallToolResult(
            content=[{"type": "text", "text": "SSE retry shim exceeded round limit."}],  # type: ignore[list-item]
            is_error=True,
        )

    return wrapped


# ─── Option D: dispatch by version (comparison artifact) ─────────────────────


def dispatch_by_version(
    *,
    mrtr: MrtrHandler,
    sse: Callable[[Any, CallToolRequestParams], Awaitable[CallToolResult]],
    min_mrtr_version: str = "2026-06-01",
) -> MrtrHandler:
    """Two handlers, one per protocol era. SDK picks by negotiated version.

    No shim, no magic — the author wrote both paths, the SDK just routes.
    Two functions per tool, both live until SSE is deprecated, and nothing
    mechanically links them: if the MRTR handler changes the elicitation
    schema and the SSE handler doesn't, nothing catches it.
    """

    async def wrapped(ctx: Any, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
        version = ctx.session.client_params.protocol_version if ctx.session.client_params else None
        if version is not None and str(version) >= min_mrtr_version:
            return await mrtr(ctx, params)
        return await sse(ctx, params)

    return wrapped
