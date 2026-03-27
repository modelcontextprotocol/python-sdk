"""Option B: exception-based shim, ``await elicit()`` canonical. The footgun.

Tool author writes today's ``await ctx.elicit(...)`` style. The shim routes:
  - old client → native SSE, blocks inline (today's behaviour exactly)
  - new client → ``elicit()`` raises ``NeedsInputSignal``, shim catches,
    emits ``IncompleteResult``. On retry the handler runs *from the top*
    and this time ``elicit()`` finds the answer in ``input_responses``.

Author experience: zero migration. Handlers that work today keep working.
The ``await`` reads linearly.

The problem: the ``await`` is a lie on MRTR sessions. Everything above it
re-executes on retry. Uncomment the ``audit_log()`` call below — an MRTR
client triggers *two* audit entries for one tool call. A pre-MRTR client
triggers one. Same source, different observable behaviour, nothing warns.

Only safe if you can enforce "no side-effects before await" as a lint
rule, which is hard in practice.

**This is not a ship target — it's a cautionary comparison.**
"""

from __future__ import annotations

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.experimental.mrtr import input_response

from ._shared import UNITS_REQUEST, UNITS_SCHEMA, build_server, lookup_weather


class NeedsInputSignal(Exception):
    """Control-flow-by-exception. Unwound by the shim, packaged as IncompleteResult."""

    def __init__(self, input_requests: types.InputRequests) -> None:
        self.input_requests = input_requests
        super().__init__("NeedsInputSignal (control flow, not an error)")


async def elicit_or_signal(
    ctx: ServerRequestContext, params: types.CallToolRequestParams, key: str
) -> dict[str, str] | None:
    """The ``await``-able elicit that looks linear but isn't on MRTR."""
    version = ctx.session.client_params.protocol_version if ctx.session.client_params else None

    # Old client: native SSE, no trickery.
    if version is None or str(version) < "2026-06-01":
        result = await ctx.session.elicit_form(message="Which units?", requested_schema=UNITS_SCHEMA)
        if result.action != "accept" or not result.content:
            return None
        return {k: str(v) for k, v in result.content.items()}

    # New client: check input_responses first.
    prefs = input_response(params, key)
    if prefs is not None:
        return {k: str(v) for k, v in prefs.items()}

    # Not pre-supplied → signal the shim. Everything on the stack unwinds.
    # On retry the handler re-executes from line one.
    raise NeedsInputSignal({key: UNITS_REQUEST})


# ───────────────────────────────────────────────────────────────────────────
# This is what the tool author writes. Looks linear. Isn't, on MRTR.
# ───────────────────────────────────────────────────────────────────────────


async def _weather_inner(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    location = (params.arguments or {}).get("location", "?")

    # audit_log(location)
    #   ^^^^^^^^^^^^^^^^^^
    #   On pre-MRTR: runs once. On MRTR: runs once on the initial call,
    #   once more on the retry. The await below isn't a suspension point
    #   on MRTR — it's a re-entry point. Nothing in this syntax says so.

    prefs = await elicit_or_signal(ctx, params, "units")
    if not prefs:
        return types.CallToolResult(content=[types.TextContent(text="Cancelled.")])

    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


async def weather(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    try:
        return await _weather_inner(ctx, params)
    except NeedsInputSignal as signal:
        return types.IncompleteResult(input_requests=signal.input_requests)


server = build_server("mrtr-option-b", on_call_tool=weather)
