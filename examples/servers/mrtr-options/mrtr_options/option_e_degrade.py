"""Option E: graceful degradation. The SDK default.

Tool author writes MRTR-native code only. Pre-MRTR clients get a result
with a default (or an error — author's choice) for *this tool*; everything
else on the server is unaffected. Version negotiation succeeds, tools/list
is complete, tools that don't elicit work normally.

This is the only option that works on horizontally-scaled MRTR-only infra,
and it's also correct on SSE-capable infra — both quadrant rows collapse
here. That's why it's the default: a server adopting the new SDK gets this
behaviour without asking. A/C/D are opt-in for servers that choose to carry
SSE through the transition.

Author experience: one code path, trivially understood. The version check
is one line at the top; everything below is plain MRTR.
"""

from __future__ import annotations

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.experimental.mrtr import input_response

from ._shared import UNITS_REQUEST, build_server, lookup_weather

MRTR_MIN_VERSION = "2026-06-01"


async def weather(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    location = (params.arguments or {}).get("location", "?")

    # ───────────────────────────────────────────────────────────────────────
    # Pre-MRTR session: elicitation unavailable. Tool author decides what
    # that means — not the SDK, not the spec.
    #
    # For weather, unit preference is nice-to-have. Defaulting to metric
    # and returning the answer is a better old-client experience than
    # "upgrade your client to check the weather."
    #
    # For a tool where the elicitation is essential — confirming a
    # destructive action, collecting required auth — error instead:
    #
    #   return types.CallToolResult(
    #       content=[types.TextContent(
    #           text=f"This tool requires protocol version {MRTR_MIN_VERSION}+."
    #       )],
    #       is_error=True,
    #   )
    #
    # Either way: no SSE code path. The server is still a valid 2025-11
    # server — it just doesn't use the client's declared elicitation
    # capability. Servers are already allowed to do that. No new flags,
    # no special negotiation.
    # ───────────────────────────────────────────────────────────────────────
    version = ctx.session.client_params.protocol_version if ctx.session.client_params else None
    if version is None or str(version) < MRTR_MIN_VERSION:
        return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, "metric"))])

    prefs = input_response(params, "units")
    if prefs is None:
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})

    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


server = build_server("mrtr-option-e", on_call_tool=weather)
