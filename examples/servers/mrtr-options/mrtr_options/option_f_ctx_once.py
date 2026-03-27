"""Option F: ``ctx.once`` idempotency guard inside the monolithic handler.

Same MRTR-native shape as E, but side-effects get wrapped in
``ctx.once(key, fn)``. The guard lives in ``request_state`` — on retry,
keys marked executed skip their fn. Makes the hazard *visible* at the
call site without restructuring the handler.

Opt-in: an unwrapped mutation still fires twice. The footgun isn't
eliminated — it's made reviewable. ``ctx.once("x", ...)`` reads
differently from a bare call; a reviewer can grep for effects that
aren't wrapped.

When to reach for this over G (ToolBuilder): single elicitation, one
or two side-effects, handler fits in ten lines. When the step count
hits 3+, ToolBuilder's boilerplate pays for itself.
"""

from __future__ import annotations

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.experimental.mrtr import MrtrCtx, input_response

from ._shared import UNITS_REQUEST, audit_log, build_server, lookup_weather


async def weather(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    location = (params.arguments or {}).get("location", "?")
    mrtr = MrtrCtx(params)

    # ───────────────────────────────────────────────────────────────────────
    # This is the hazard line. In E it would run on every retry.
    # Here it runs once — ``once`` checks request_state, skips on retry.
    # A reviewer sees ``mrtr.once`` and knows the author considered
    # re-entry. A bare ``audit_log(location)`` would be the red flag.
    # ───────────────────────────────────────────────────────────────────────
    mrtr.once("audit", lambda: audit_log(location))

    prefs = input_response(params, "units")
    if prefs is None:
        # ``mrtr.incomplete()`` encodes the executed-keys set into
        # request_state so the guard holds across retry.
        return mrtr.incomplete({"units": UNITS_REQUEST})

    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


server = build_server("mrtr-option-f", on_call_tool=weather)
