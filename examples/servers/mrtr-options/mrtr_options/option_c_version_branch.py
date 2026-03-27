"""Option C: explicit version branch in the handler body.

No shim. Tool author checks the negotiated version themselves and writes
both code paths inline. The SDK provides nothing except the version
accessor and the raw primitives for each path.

Author experience: everything is visible. Both protocol behaviours are
right there in source, separated by an ``if``. No hidden re-entry, no
magic wrappers. A reader traces exactly what happens for each client
version.

The cost is also visible: the elicitation schema is duplicated, the
cancel-handling is duplicated, and there's a conditional at the top of
every handler that uses elicitation. For one tool, fine. For twenty,
it's twenty copies of the same branch.
"""

from __future__ import annotations

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.experimental.mrtr import input_response

from ._shared import UNITS_REQUEST, UNITS_SCHEMA, build_server, lookup_weather


async def weather(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    location = (params.arguments or {}).get("location", "?")
    version = ctx.session.client_params.protocol_version if ctx.session.client_params else None

    # ───────────────────────────────────────────────────────────────────────
    # The branch is the whole story.
    # ───────────────────────────────────────────────────────────────────────

    if version is not None and str(version) >= "2026-06-01":
        # MRTR path: check input_responses, return IncompleteResult if missing.
        prefs = input_response(params, "units")
        if prefs is None:
            return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})
        return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])

    # SSE path: inline await, blocks on the response stream.
    result = await ctx.session.elicit_form(message="Which units?", requested_schema=UNITS_SCHEMA)
    if result.action != "accept" or not result.content:
        return types.CallToolResult(content=[types.TextContent(text="Cancelled.")])
    units = str(result.content.get("units", "metric"))
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, units))])


server = build_server("mrtr-option-c", on_call_tool=weather)
