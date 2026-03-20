"""Option A: SDK shim emulates the MRTR retry loop over SSE. Hidden loop.

Tool author writes MRTR-native code only. The SDK wrapper detects the
negotiated version:
  - new client → pass ``IncompleteResult`` through, client drives retry
  - old client → SDK runs the retry loop *locally*, fulfilling each
    ``InputRequest`` via real SSE (``ctx.session.elicit_form()``),
    re-invoking the handler until it returns a complete result

Author experience: one code path. Re-entry is explicit in source (the
``if not prefs`` guard), so the handler is safe to re-invoke by
construction. But the *fact* that it's re-invoked for old clients is
invisible — the shim is doing work the author can't see.

What makes this "clunky but possible": the SDK runs a loop on the
author's behalf. If the handler does something expensive before the
guard, the author won't find out until an old client connects in prod.
Works, but it's magic.

Deployment hazard: ``sse_retry_shim`` calls real SSE under the hood.
On MRTR-only infra it fails at runtime when an old client connects —
a constraint that lives nowhere near the tool code. If that's the
deployment, use Option E.
"""

from __future__ import annotations

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.experimental.mrtr import input_response, sse_retry_shim

from ._shared import UNITS_REQUEST, build_server, lookup_weather

# ───────────────────────────────────────────────────────────────────────────
# This is what the tool author writes. One function, MRTR-native. No
# version check, no SSE awareness. The ``if not prefs`` guard IS the
# re-entry contract; the author sees it, but doesn't see the shim
# calling this in a loop for old-client sessions.
# ───────────────────────────────────────────────────────────────────────────


async def weather(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    location = (params.arguments or {}).get("location", "?")

    prefs = input_response(params, "units")
    if prefs is None:
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})

    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


# ───────────────────────────────────────────────────────────────────────────
# Registration applies the shim. In a real SDK this could be a flag on
# ``add_tool`` or inferred from the handler signature — the author opts in
# once at registration, not per-call.
# ───────────────────────────────────────────────────────────────────────────

server = build_server("mrtr-option-a", on_call_tool=sse_retry_shim(weather))
