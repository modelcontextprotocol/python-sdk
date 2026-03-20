"""Option G: ``ToolBuilder`` — explicit step decomposition.

The monolithic handler becomes a sequence of named step functions.
``incomplete_step`` may return ``IncompleteResult`` (needs more input)
or a dict (satisfied, pass to next step). ``end_step`` receives
everything and runs exactly once — structurally unreachable until
every prior step has returned data.

The footgun is eliminated by code shape, not discipline. There is no
"above the guard" zone because there is no guard — the SDK's step
tracking (via ``request_state``) *is* the guard. Side-effects go in
``end_step``; anything in an ``incomplete_step`` is documented as
must-be-idempotent, and the return-type split makes that distinction
visible at the function signature level.

Boilerplate: two function defs + ``.build()`` to replace E's 3-line
guard. Worth it at 3+ rounds or when the side-effect story matters.
Overkill for a single-question tool where F is lighter.
"""

from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server.experimental.mrtr import ToolBuilder

from ._shared import UNITS_REQUEST, audit_log, build_server, lookup_weather

# ───────────────────────────────────────────────────────────────────────────
# Step 1: ask for units. Returns IncompleteResult if not yet provided,
# or ``{"units": ...}`` to pass forward. MUST be idempotent — it can
# re-run if request_state is tampered with (unsigned in this draft) or
# on a partial replay. No side-effects here.
# ───────────────────────────────────────────────────────────────────────────


def ask_units(args: dict[str, Any], inputs: dict[str, Any]) -> types.IncompleteResult | dict[str, Any]:
    resp = inputs.get("units")
    if not resp or resp.get("action") != "accept":
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})
    return {"units": resp["content"]["units"]}


# ───────────────────────────────────────────────────────────────────────────
# End step: has everything, does the work. Runs exactly once. This is
# where side-effects live — the SDK guarantees this function is not
# reached until ``ask_units`` (and any other incomplete steps) have all
# returned data. ``audit_log`` here fires once regardless of how many
# MRTR rounds it took to collect the inputs.
# ───────────────────────────────────────────────────────────────────────────


def fetch_weather(args: dict[str, Any], collected: dict[str, Any]) -> types.CallToolResult:
    location = (args or {}).get("location", "?")
    audit_log(location)
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, collected["units"]))])


# ───────────────────────────────────────────────────────────────────────────
# Assembly. Steps are named so reordering during development doesn't
# silently remap data. The builder output is directly a lowlevel
# ``on_call_tool`` handler — no extra wrapping.
# ───────────────────────────────────────────────────────────────────────────

weather = ToolBuilder[dict[str, Any]]().incomplete_step("ask_units", ask_units).end_step(fetch_weather).build()

server = build_server("mrtr-option-g", on_call_tool=weather)
