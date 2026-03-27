"""Domain logic shared across all options — *not* SDK machinery.

The weather tool: given a location, asks which units, returns a temperature
string. Same tool throughout so the diff between option files is the
argument.

``audit_log`` is the side-effect that makes the MRTR footgun concrete: under
naive re-entry it fires once per round. Options F and G tame it.
"""

from __future__ import annotations

from mcp import types
from mcp.server import Server, ServerRequestContext

UNITS_SCHEMA: types.ElicitRequestedSchema = {
    "type": "object",
    "properties": {"units": {"type": "string", "enum": ["metric", "imperial"], "title": "Units"}},
    "required": ["units"],
}

UNITS_REQUEST = types.ElicitRequest(
    params=types.ElicitRequestFormParams(message="Which units?", requested_schema=UNITS_SCHEMA)
)


def lookup_weather(location: str, units: str) -> str:
    temp = "22°C" if units == "metric" else "72°F"
    return f"Weather in {location}: {temp}, partly cloudy."


_audit_count = 0


def audit_log(location: str) -> None:
    """The footgun. Under naive re-entry this fires N times for N-round MRTR."""
    global _audit_count
    _audit_count += 1
    print(f"[audit] lookup requested for {location} (count={_audit_count})")


def audit_count() -> int:
    return _audit_count


def reset_audit() -> None:
    global _audit_count
    _audit_count = 0


async def no_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
    """Minimal tools/list handler so Client validation has something to call."""
    return types.ListToolsResult(tools=[])


def build_server(name: str, on_call_tool: object, **kwargs: object) -> Server:
    """Consistent Server construction across option files."""
    return Server(name, on_call_tool=on_call_tool, on_list_tools=no_tools, **kwargs)  # type: ignore[arg-type]
