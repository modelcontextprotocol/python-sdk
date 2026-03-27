"""Option D: dual registration. Two handlers, SDK picks by version.

Tool author writes two separate functions — one MRTR-native, one
SSE-native — and hands both to the SDK. Dispatch by negotiated version.
No shim converts between them; each path is exactly what the author
wrote for that protocol era.

Author experience: no hidden control flow. Unlike Option C, the two
paths are structurally separated rather than tangled in one body.
Shared logic factors out naturally. Each handler readable in isolation.

The cost: two functions per elicitation-using tool, both live until SSE
is deprecated. There's no mechanical link between them — if the MRTR
handler changes the schema and the SSE one doesn't, nothing catches it.
Also: the registration API grows a shape that only exists for the
transition period.
"""

from __future__ import annotations

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.experimental.mrtr import dispatch_by_version, input_response

from ._shared import UNITS_REQUEST, UNITS_SCHEMA, build_server, lookup_weather

# ───────────────────────────────────────────────────────────────────────────
# Two functions. Each clean in isolation.
# ───────────────────────────────────────────────────────────────────────────


async def weather_mrtr(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    location = (params.arguments or {}).get("location", "?")
    prefs = input_response(params, "units")
    if prefs is None:
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


async def weather_sse(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    location = (params.arguments or {}).get("location", "?")
    result = await ctx.session.elicit_form(message="Which units?", requested_schema=UNITS_SCHEMA)
    if result.action != "accept" or not result.content:
        return types.CallToolResult(content=[types.TextContent(text="Cancelled.")])
    units = str(result.content.get("units", "metric"))
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, units))])


# ───────────────────────────────────────────────────────────────────────────
# Registration takes both. Real SDK shape might be an overload or a
# ``{mrtr:, sse:}`` dict — point is both handlers are visible at the
# registration site and the SDK owns the switch.
# ───────────────────────────────────────────────────────────────────────────

server = build_server("mrtr-option-d", on_call_tool=dispatch_by_version(mrtr=weather_mrtr, sse=weather_sse))
