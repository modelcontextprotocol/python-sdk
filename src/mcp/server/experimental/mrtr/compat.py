"""Dual-path compat shims for pre-MRTR clients (Options A and D).

!!! warning "Comparison artifacts, not ship targets"
    These exist so the option-comparison deck has concrete SDK machinery to
    reference. Whether either ships depends on where SEP-2322 discussion
    converges. Option E (degrade-only) is the SDK default and requires
    neither.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import CallToolRequestParams, CallToolResult, ElicitRequest, ElicitRequestFormParams, IncompleteResult

MrtrHandler = Callable[[Any, CallToolRequestParams], Awaitable[CallToolResult | IncompleteResult]]
"""Signature of an MRTR-native lowlevel handler."""

MRTR_MIN_VERSION = "2026-06-01"
"""Placeholder for the first protocol version where IncompleteResult is legal."""


def sse_retry_shim(mrtr_handler: MrtrHandler, *, max_rounds: int = 8) -> MrtrHandler:  # pragma: no cover
    """Wrap an MRTR-native handler so pre-MRTR clients also get elicitation (Option A).

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

    Not tested against a pre-MRTR client in this draft because the SDK's
    LATEST_PROTOCOL_VERSION is still 2025-11-25. Covered by E2E tests once
    the version bumps.
    """

    async def wrapped(ctx: Any, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
        version = ctx.session.client_params.protocol_version if ctx.session.client_params else None
        if version is None or str(version) >= MRTR_MIN_VERSION:
            return await mrtr_handler(ctx, params)

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


def dispatch_by_version(
    *,
    mrtr: MrtrHandler,
    sse: Callable[[Any, CallToolRequestParams], Awaitable[CallToolResult]],
    min_mrtr_version: str = MRTR_MIN_VERSION,
) -> MrtrHandler:
    """Two handlers, one per protocol era. SDK picks by negotiated version (Option D).

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
