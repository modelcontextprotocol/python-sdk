"""Option H: continuation-based linear MRTR. ``await ctx.elicit()`` is genuine.

The Option B footgun was: ``await elicit()`` *looks* like a suspension point
but is actually a re-entry point, so everything above it runs twice. This
fixes that by making it a *real* suspension point — the coroutine frame is
held in a ``ContinuationStore`` across MRTR rounds, keyed by
``request_state``.

Handler code stays exactly as it was in the SSE era. Side-effects above
the await fire once because the function never restarts — it resumes.

Trade-off: the server holds the frame in memory between rounds. Client
still sees pure MRTR (no SSE), but the server is stateful *within* a
single tool call. Horizontally-scaled deployments need sticky routing on
the ``request_state`` token. Same operational shape as Option A's SSE
hold, without the long-lived connection.

When to use: migrating existing SSE-era tools to MRTR wire protocol
without rewriting the handler, or when the linear style is genuinely
clearer than guard-first (complex branching, many rounds).

When not to: if you need true statelessness across server instances.
Use E/F/G — they encode everything the server needs in ``request_state``
itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mcp.server.experimental.mrtr import ContinuationStore, LinearCtx, linear_mrtr

from ._shared import audit_log, build_server, lookup_weather


class UnitsPref(BaseModel):
    units: str


# ───────────────────────────────────────────────────────────────────────────
# This is what the tool author writes. Linear, front-to-back, no re-entry
# contract to reason about. The ``audit_log`` above the await fires
# exactly once — the await is a real suspension point.
# ───────────────────────────────────────────────────────────────────────────


async def weather(ctx: LinearCtx, args: dict[str, Any]) -> str:
    location = args["location"]
    audit_log(location)  # runs once — unlike Option B
    prefs = await ctx.elicit("Which units?", UnitsPref)
    return lookup_weather(location, prefs.units)


# ───────────────────────────────────────────────────────────────────────────
# Registration. The store must be entered as an async context manager
# around the server's run loop — it owns the task group that keeps the
# suspended coroutines alive.
# ───────────────────────────────────────────────────────────────────────────

store = ContinuationStore()
server = build_server("mrtr-option-h", on_call_tool=linear_mrtr(weather, store=store))
