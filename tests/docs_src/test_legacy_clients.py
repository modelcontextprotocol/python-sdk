"""`docs/run/legacy-clients.md`: every claim the page makes, proved against the real SDK."""

import inspect

import httpx
import pytest
from mcp_types import INVALID_REQUEST, ResourceUpdatedNotification, TextContent

from docs_src.legacy_clients import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "b", "version": "1"}},
}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
URL = "http://localhost:8000/mcp"


async def test_one_resolve_tool_serves_a_legacy_and_a_modern_client_at_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """tutorial001's `main()`, exactly as the page renders it: two eras of client, one server, one answer."""
    await tutorial001.main()
    assert capsys.readouterr().out == (
        """2025-11-25 {'result': "Reserved 2 of 'Dune'."}\n2026-07-28 {'result': "Reserved 2 of 'Dune'."}\n"""
    )


async def test_neither_era_of_client_sees_the_resolved_parameter() -> None:
    """tutorial001: there is one tool schema. The `Resolve`-filled parameter is hidden from both eras."""
    async with Client(tutorial001.mcp, mode="legacy") as legacy, Client(tutorial001.mcp) as modern:
        for client in (legacy, modern):
            (tool,) = (await client.list_tools()).tools
            assert set(tool.input_schema["properties"]) == {"title"}


def test_streamable_http_app_has_no_era_knob() -> None:
    """The opener: nothing in `streamable_http_app()`'s signature selects, rejects, or configures an era."""
    parameters = set(inspect.signature(MCPServer.streamable_http_app).parameters) - {"self"}
    assert parameters == {
        "streamable_http_path",
        "json_response",
        "stateless_http",
        "event_store",
        "retry_interval",
        "transport_security",
        "host",
    }


async def test_a_legacy_session_is_minted_in_process_and_a_stray_session_id_is_a_404() -> None:
    """The cost section: a legacy `initialize` gets an `Mcp-Session-Id`, and a request naming a session
    this process never minted gets a `404`. That miss is exactly what a load balancer without sticky
    routing produces."""
    app = MCPServer("Bookshop").streamable_http_app()
    async with (
        app.router.lifespan_context(app),
        httpx.ASGITransport(app) as transport,
        httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as http,
    ):
        opened = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert opened.status_code == 200
        assert opened.headers["mcp-session-id"]

        stray = await http.post("/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, "Mcp-Session-Id": 32 * "f"})
        assert stray.status_code == 404


async def test_stateless_http_never_mints_a_session() -> None:
    """The `stateless_http=True` section: the same legacy `initialize` no longer gets an `Mcp-Session-Id`."""
    app = MCPServer("Bookshop").streamable_http_app(stateless_http=True)
    async with (
        app.router.lifespan_context(app),
        httpx.ASGITransport(app) as transport,
        httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as http,
    ):
        opened = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert opened.status_code == 200
    assert "mcp-session-id" not in opened.headers


async def test_stateless_http_kills_the_legacy_back_channel_and_only_the_legacy_one() -> None:
    """tutorial002: over the same `stateless_http=True` app, the modern client still gets its answer and
    the legacy client's call fails as the top-level `MCPError` the `!!! check` quotes."""
    async with (
        tutorial002.app.router.lifespan_context(tutorial002.app),
        httpx.ASGITransport(tutorial002.app) as transport,
        httpx.AsyncClient(transport=transport) as http,
    ):
        modern_target = streamable_http_client(URL, http_client=http)
        async with Client(modern_target, elicitation_callback=tutorial001.answer) as modern:
            assert modern.protocol_version == "2026-07-28"
            result = await modern.call_tool("reserve", {"title": "Dune"})
            assert result.content == [TextContent(type="text", text="Reserved 2 of 'Dune'.")]

        legacy_target = streamable_http_client(URL, http_client=http)
        async with Client(legacy_target, mode="legacy", elicitation_callback=tutorial001.answer) as legacy:
            assert legacy.protocol_version == "2025-11-25"
            with pytest.raises(MCPError) as exc_info:  # pragma: no branch
                await legacy.call_tool("reserve", {"title": "Dune"})
    assert exc_info.value.error.code == INVALID_REQUEST
    assert exc_info.value.error.message == (
        "Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests."
    )


async def test_the_legacy_notification_verb_reaches_a_legacy_client() -> None:
    """tutorial003: `ctx.session.send_resource_updated` lands on the legacy client's standalone stream."""
    received: list[object] = []

    async def on_message(message: object) -> None:
        received.append(message)

    async with Client(tutorial003.mcp, mode="legacy", message_handler=on_message) as client:
        result = await client.call_tool("restock", {"title": "Dune", "copies": 2})
        assert not result.is_error
    (notification,) = received
    assert isinstance(notification, ResourceUpdatedNotification)
    assert notification.params.uri == "stock://Dune"


async def test_calling_both_notification_verbs_is_safe_on_both_eras() -> None:
    """tutorial003: the two-line fork never errors, whichever era the caller is on."""
    async with Client(tutorial003.mcp, mode="legacy") as legacy, Client(tutorial003.mcp) as modern:
        for client in (legacy, modern):
            result = await client.call_tool("restock", {"title": "Dune", "copies": 1})
            assert not result.is_error
