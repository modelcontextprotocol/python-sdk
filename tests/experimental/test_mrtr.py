"""E2E tests for MRTR server-side primitives (SEP-2322).

Tests the ``mcp.server.experimental.mrtr`` module: ``MrtrCtx``,
``ToolBuilder``, ``input_response``, ``dispatch_by_version``.

The footgun test measures side-effect counts to prove F and G actually
hold the guard. The invariant test parametrises all handler shapes against
the same Client to prove the server's internal choice doesn't leak.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.client.client import Client
from mcp.client.context import ClientRequestContext
from mcp.server import Server, ServerRequestContext
from mcp.server.experimental.mrtr import MrtrCtx, ToolBuilder, dispatch_by_version, input_response

pytestmark = pytest.mark.anyio


# ─── Shared domain bits (mirror of examples/servers/mrtr-options) ────────────


UNITS_REQUEST = types.ElicitRequest(
    params=types.ElicitRequestFormParams(
        message="Which units?",
        requested_schema={
            "type": "object",
            "properties": {"units": {"type": "string", "enum": ["metric", "imperial"]}},
            "required": ["units"],
        },
    )
)


def lookup_weather(location: str, units: str) -> str:
    temp = "22°C" if units == "metric" else "72°F"
    return f"Weather in {location}: {temp}"


async def no_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[])


async def pick_metric(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    return types.ElicitResult(action="accept", content={"units": "metric"})


_audit: list[str] = []


def audit_log(where: str) -> None:
    _audit.append(where)


@pytest.fixture(autouse=True)
def reset_audit():
    _audit.clear()
    yield


MrtrHandler = Callable[
    [ServerRequestContext, types.CallToolRequestParams], Awaitable[types.CallToolResult | types.IncompleteResult]
]


def make_server(handler: MrtrHandler) -> Server:
    return Server("mrtr-test", on_call_tool=handler, on_list_tools=no_tools)


# ─── Handler shapes ──────────────────────────────────────────────────────────


async def option_e_degrade(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    """Option E — SDK default. MRTR-native; pre-MRTR gets default."""
    location = (params.arguments or {}).get("location", "?")
    prefs = input_response(params, "units")
    if prefs is None:
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


async def option_f_ctx_once(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    """Option F — ctx.once idempotency guard."""
    location = (params.arguments or {}).get("location", "?")
    mrtr = MrtrCtx(params)
    mrtr.once("audit", lambda: audit_log(f"F:{location}"))
    prefs = input_response(params, "units")
    if prefs is None:
        return mrtr.incomplete({"units": UNITS_REQUEST})
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


def ask_units(args: dict[str, Any], inputs: dict[str, Any]) -> types.IncompleteResult | dict[str, Any]:
    resp = inputs.get("units")
    if not resp or resp.get("action") != "accept":
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})
    return {"units": resp["content"]["units"]}


def fetch_weather(args: dict[str, Any], collected: dict[str, Any]) -> types.CallToolResult:
    location = (args or {}).get("location", "?")
    audit_log(f"G:{location}")
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, collected["units"]))])


option_g_tool_builder = (
    ToolBuilder[dict[str, Any]]().incomplete_step("ask_units", ask_units).end_step(fetch_weather).build()
)


async def option_e_with_naive_audit(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    """Option E with a naive side-effect above the guard — the footgun."""
    location = (params.arguments or {}).get("location", "?")
    audit_log(f"naive:{location}")  # runs on EVERY round
    prefs = input_response(params, "units")
    if prefs is None:
        return types.IncompleteResult(input_requests={"units": UNITS_REQUEST})
    return types.CallToolResult(content=[types.TextContent(text=lookup_weather(location, prefs["units"]))])


# ─── The invariant: client can't tell ────────────────────────────────────────


@pytest.mark.parametrize(
    "handler",
    [option_e_degrade, option_f_ctx_once, option_g_tool_builder],
    ids=["E-degrade", "F-ctx_once", "G-tool_builder"],
)
async def test_mrtr_wire_invariant(handler: MrtrHandler):
    """All MRTR handler shapes produce identical wire behaviour.

    The server's internal choice (guard-first, ctx.once, ToolBuilder) doesn't
    leak to the client. Same Client, same callback, same result. This is the
    argument against per-feature ``-mrtr`` capability flags.
    """
    async with Client(make_server(handler), elicitation_callback=pick_metric) as client:
        result = await client.call_tool("weather", {"location": "Tokyo"})
        assert isinstance(result, types.CallToolResult)
        assert result.content[0] == types.TextContent(text="Weather in Tokyo: 22°C")


# ─── The footgun: side-effect counts ─────────────────────────────────────────


async def test_mrtr_naive_handler_double_executes_side_effect():
    """The footgun, measured. Naive MRTR handler fires audit_log twice."""
    async with Client(make_server(option_e_with_naive_audit), elicitation_callback=pick_metric) as client:
        await client.call_tool("weather", {"location": "Tokyo"})
    assert _audit == snapshot(["naive:Tokyo", "naive:Tokyo"])


async def test_mrtr_ctx_once_holds_side_effect():
    """Option F: ctx.once guard holds the side-effect to one across retry."""
    async with Client(make_server(option_f_ctx_once), elicitation_callback=pick_metric) as client:
        await client.call_tool("weather", {"location": "Tokyo"})
    assert _audit == snapshot(["F:Tokyo"])


async def test_mrtr_tool_builder_end_step_runs_once():
    """Option G: end_step runs exactly once regardless of round count."""
    async with Client(make_server(option_g_tool_builder), elicitation_callback=pick_metric) as client:
        await client.call_tool("weather", {"location": "Tokyo"})
    assert _audit == snapshot(["G:Tokyo"])


# ─── ToolBuilder edge cases ──────────────────────────────────────────────────


def test_tool_builder_requires_end_step():
    with pytest.raises(ValueError, match="end_step is required"):
        ToolBuilder[dict[str, Any]]().incomplete_step("x", ask_units).build()


def test_tool_builder_rejects_duplicate_step_names():
    with pytest.raises(ValueError, match="duplicate step names"):
        ToolBuilder[dict[str, Any]]().incomplete_step("x", ask_units).incomplete_step("x", ask_units).end_step(
            fetch_weather
        ).build()


async def test_tool_builder_multi_step_accumulates():
    """Two incomplete_steps before end_step — collected dict merges."""

    def ask_lang(args: dict[str, Any], inputs: dict[str, Any]) -> types.IncompleteResult | dict[str, Any]:
        resp = inputs.get("lang")
        if not resp or resp.get("action") != "accept":
            return types.IncompleteResult(
                input_requests={
                    "lang": types.ElicitRequest(
                        params=types.ElicitRequestFormParams(message="Lang?", requested_schema={})
                    )
                }
            )
        return {"lang": resp["content"]["lang"]}

    def finish(args: dict[str, Any], collected: dict[str, Any]) -> types.CallToolResult:
        return types.CallToolResult(content=[types.TextContent(text=f"{collected['units']}/{collected['lang']}")])

    handler = (
        ToolBuilder[dict[str, Any]]()
        .incomplete_step("ask_units", ask_units)
        .incomplete_step("ask_lang", ask_lang)
        .end_step(finish)
        .build()
    )

    answers = {"Which units?": {"units": "metric"}, "Lang?": {"lang": "en"}}

    async def elicitation_cb(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
        assert isinstance(params, types.ElicitRequestFormParams)
        return types.ElicitResult(action="accept", content=dict(answers[params.message]))

    async with Client(make_server(handler), elicitation_callback=elicitation_cb) as client:
        result = await client.call_tool("multi", {})
        assert result == snapshot(types.CallToolResult(content=[types.TextContent(text="metric/en")]))


# ─── MrtrCtx edge cases ──────────────────────────────────────────────────────


async def test_mrtr_ctx_once_persists_across_multiple_rounds():
    """once() guard survives 3+ rounds — executed-keys round-trip through request_state."""

    async def handler(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult | types.IncompleteResult:
        mrtr = MrtrCtx(params)
        mrtr.once("init", lambda: audit_log("init"))

        # Step progression tracked via executed keys, not raw input_responses
        # (which only carries the latest round's answers per SEP).
        if not mrtr.has_run("got_a"):
            if not input_response(params, "a"):
                return mrtr.incomplete({"a": UNITS_REQUEST})
            mrtr.once("got_a", lambda: audit_log("after_a"))

        if not input_response(params, "b"):
            return mrtr.incomplete({"b": UNITS_REQUEST})
        mrtr.once("got_b", lambda: audit_log("after_b"))
        return types.CallToolResult(content=[types.TextContent(text="done")])

    async def elicitation_cb(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
        return types.ElicitResult(action="accept", content={"units": "metric"})

    async with Client(make_server(handler), elicitation_callback=elicitation_cb) as client:
        await client.call_tool("multi", {})

    assert _audit == snapshot(["init", "after_a", "after_b"])


# ─── input_response helper ───────────────────────────────────────────────────


def test_input_response_returns_none_on_missing():
    params = types.CallToolRequestParams(name="x")
    assert input_response(params, "key") is None


def test_input_response_returns_none_on_decline():
    params = types.CallToolRequestParams(name="x", input_responses={"key": {"action": "decline"}})
    assert input_response(params, "key") is None


def test_input_response_returns_content_on_accept():
    params = types.CallToolRequestParams(name="x", input_responses={"key": {"action": "accept", "content": {"v": 1}}})
    assert input_response(params, "key") == {"v": 1}


# ─── dispatch_by_version ─────────────────────────────────────────────────────


async def _mrtr_path(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text="mrtr")])


async def _sse_path(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text="sse")])


async def test_dispatch_by_version_routes_to_mrtr_when_at_or_above():
    """Negotiated version >= min → MRTR handler."""
    handler = dispatch_by_version(mrtr=_mrtr_path, sse=_sse_path, min_mrtr_version=types.LATEST_PROTOCOL_VERSION)
    async with Client(make_server(handler)) as client:
        result = await client.call_tool("x", {})
        assert result == snapshot(types.CallToolResult(content=[types.TextContent(text="mrtr")]))


async def test_dispatch_by_version_routes_to_sse_when_below():
    """Negotiated version < min → SSE handler."""
    handler = dispatch_by_version(mrtr=_mrtr_path, sse=_sse_path, min_mrtr_version="9999-01-01")
    async with Client(make_server(handler)) as client:
        result = await client.call_tool("x", {})
        assert result == snapshot(types.CallToolResult(content=[types.TextContent(text="sse")]))
