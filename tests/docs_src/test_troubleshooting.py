"""`docs/troubleshooting.md`: every error string the page names, reproduced against the real SDK."""

import logging
from typing import Any

import httpx
import pytest
from mcp_types import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    TextContent,
)

from docs_src.troubleshooting import (
    tutorial001,
    tutorial002,
    tutorial003,
    tutorial004,
    tutorial005,
    tutorial006,
    tutorial007,
    tutorial008,
)
from mcp import Client, MCPError
from mcp.client import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.mcpserver import RequestStateSecurity

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "b", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def _confirm(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    """The page's one `elicitation_callback`: always accept the booking."""
    return ElicitResult(action="accept", content={"confirm": True})


async def test_an_error_leaving_the_async_with_block_arrives_wrapped_in_an_exception_group() -> None:
    """The `unhandled errors in a TaskGroup` entry: anyio group-wraps whatever escapes the block."""
    with pytest.raises(Exception) as exc_info:
        async with Client(tutorial001.mcp) as client:
            await client.read_resource("weather://Atlantis")
    assert not isinstance(exc_info.value, MCPError)
    assert exc_info.group_contains(MCPError, match=r"^No forecast for 'Atlantis'\.$")


async def test_the_same_error_caught_inside_the_block_is_the_bare_mcp_error() -> None:
    """The fix on the page: `except MCPError` inside the `async with` never sees an `ExceptionGroup`."""
    async with Client(tutorial001.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("weather://Atlantis")
    assert str(exc_info.value) == "No forecast for 'Atlantis'."
    assert exc_info.value.error.code == INVALID_PARAMS


async def test_a_client_outside_its_async_with_refuses_every_call() -> None:
    """`Client(...)` only constructs. Nothing connects until `async with`, so every call refuses."""
    client = Client(tutorial001.mcp)
    with pytest.raises(RuntimeError, match="^Client must be used within an async context manager$"):
        await client.list_tools()


async def test_a_failing_tool_returns_is_error_true_instead_of_raising() -> None:
    """The `Error executing tool` entry: it is a result, not an exception. Nothing to `except`."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("forecast", {"city": "Atlantis"})
    assert result.is_error
    assert result.content == [
        TextContent(type="text", text="Error executing tool forecast: No forecast for 'Atlantis'.")
    ]


async def test_an_unknown_tool_is_the_same_kind_of_result() -> None:
    """`Unknown tool: <name>` travels the same `is_error=True` path as a failing tool."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("get_forecast", {"city": "London"})
    assert result.is_error
    assert result.content == [TextContent(type="text", text="Unknown tool: get_forecast")]


async def test_the_tool_decorator_without_parentheses_raises_at_import_time() -> None:
    """`@mcp.tool` (no parentheses) hands the function itself to `name=`; the SDK refuses immediately."""
    mcp = MCPServer("Weather")
    undecorated: Any = mcp.tool
    with pytest.raises(TypeError, match=r"Use @tool\(\) instead of @tool"):

        @undecorated
        def forecast(city: str) -> str:
            """Today's forecast for one city."""
            return f"{city}: Rain."


async def test_a_duplicate_tool_name_keeps_the_first_and_drops_the_second() -> None:
    """tutorial002: `tools/list` reports one `forecast`, and it is the first registration that won."""
    async with Client(tutorial002.mcp) as client:
        (tool,) = (await client.list_tools()).tools
    assert tool.name == "forecast"
    assert tool.description == "Today's forecast for one city."


async def test_a_duplicate_registration_logs_tool_already_exists(caplog: pytest.LogCaptureFixture) -> None:
    """The only signal for a dropped duplicate is the `Tool already exists:` warning in the server log."""
    with caplog.at_level(logging.WARNING, logger="mcp.server.mcpserver.tools.tool_manager"):

        @tutorial002.mcp.tool(name="forecast")
        def forecast_weekly(city: str) -> str:
            """The week ahead for one city."""
            return f"{city}: Rain all week."

    assert "Tool already exists: forecast" in caplog.messages


async def test_the_default_streamable_http_app_answers_a_real_hostname_with_421(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """tutorial003: one 421, three spellings. The page presents all three as the same event."""
    transport = httpx.ASGITransport(app=tutorial003.app)
    async with tutorial003.mcp.session_manager.run():
        # What curl (or the reverse proxy's access log) shows: the status and the plain-text body.
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp.example.com") as raw:
            with caplog.at_level(logging.WARNING, logger="mcp.server.transport_security"):
                response = await raw.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert (response.status_code, response.text) == (421, "Invalid Host header")
        # No `Content-Type: application/json`, which is exactly why the python client cannot show the body.
        assert response.headers.get("content-type") is None
        # What the server operator finds by grepping the server log.
        assert "Invalid Host header: mcp.example.com" in caplog.messages
        # What the python `Client` raises instead: the generic stand-in, wrapped by the task group.
        async with httpx.AsyncClient(transport=transport) as http_client:
            with pytest.raises(Exception) as exc_info:
                async with Client(streamable_http_client("http://mcp.example.com/mcp", http_client=http_client)):
                    pass  # never reached: the handshake itself is what fails
    assert not isinstance(exc_info.value, MCPError)
    assert exc_info.group_contains(MCPError, match="^Server returned an error response$")


async def test_an_allowlisted_hostname_connects_and_calls_a_tool() -> None:
    """tutorial004: `transport_security=` names the deployed hostname, and the same client connects."""
    transport = httpx.ASGITransport(app=tutorial004.app)
    async with tutorial004.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=transport) as http_client:
            async with Client(streamable_http_client("http://mcp.example.com/mcp", http_client=http_client)) as c:
                assert c.protocol_version == "2026-07-28"
                result = await c.call_tool("forecast", {"city": "London"})
    assert result.structured_content == {"result": "London: Rain."}


async def test_a_mounted_app_without_a_lifespan_fails_on_the_first_request() -> None:
    """tutorial005: Starlette never runs a mounted sub-app's lifespan, so nothing starts the manager."""
    transport = httpx.ASGITransport(app=tutorial005.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http:
        with pytest.raises(RuntimeError, match=r"Task group is not initialized\. Make sure to use run\(\)\."):
            await http.post("/mcp")


async def test_a_session_id_the_server_never_issued_gets_a_404_session_not_found() -> None:
    """`Session not found` is a 404 with a JSON-RPC body, so the python `Client` surfaces it verbatim."""
    mcp = MCPServer("Weather")
    app = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as h:
            response = await h.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={**MCP_HEADERS, "mcp-session-id": "deadbeef"},
            )
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Session not found"}}


async def test_ctx_elicit_at_2026_raises_method_not_found() -> None:
    """tutorial006: at 2026-07-28 there is no server-to-client `elicitation/create` for the tool to send."""
    async with Client(tutorial006.mcp) as client:
        assert client.protocol_version == "2026-07-28"
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("book_table", {"date": "Friday"})
    assert exc_info.value.error == ErrorData(
        code=METHOD_NOT_FOUND, message="Method not found", data="elicitation/create"
    )


async def test_an_elicitation_callback_does_not_fix_ctx_elicit_at_2026() -> None:
    """The page's `!!! warning`: registering the callback changes nothing. The method itself is gone."""
    async with Client(tutorial006.mcp, elicitation_callback=_confirm) as client:
        with pytest.raises(MCPError, match="^Method not found$"):
            await client.call_tool("book_table", {"date": "Friday"})


async def test_ctx_elicit_on_a_legacy_connection_works() -> None:
    """The legacy aside: `ctx.elicit` is a server-to-client request, and only a legacy session has those."""
    async with Client(tutorial006.mcp, mode="legacy", elicitation_callback=_confirm) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
    assert result.structured_content == {"result": "Booked for Friday."}


async def test_the_resolver_form_works_on_a_2026_connection() -> None:
    """tutorial007: the fix. Same question, same callback, but the server returns it instead of calling back."""
    async with Client(tutorial007.mcp, elicitation_callback=_confirm) as client:
        assert client.protocol_version == "2026-07-28"
        result = await client.call_tool("book_table", {"date": "Friday"})
    assert result.structured_content == {"result": "Booked for Friday."}


async def test_the_resolver_form_without_a_callback_names_the_missing_capability() -> None:
    """The `-32021` entry: the server refuses up front, and `data` names the capability to declare."""
    async with Client(tutorial007.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("book_table", {"date": "Friday"})
    assert exc_info.value.error == ErrorData(
        code=MISSING_REQUIRED_CLIENT_CAPABILITY,
        message=(
            "Client did not declare the form elicitation capability required by resolver "
            "'docs_src.troubleshooting.tutorial007:ask_to_confirm'"
        ),
        data={"requiredCapabilities": {"elicitation": {"form": {}}}},
    )


async def test_a_legacy_ctx_elicit_without_a_callback_says_elicitation_not_supported() -> None:
    """The `Elicitation not supported` entry: no `elicitation_callback` means nobody to ask."""
    async with Client(tutorial006.mcp, mode="legacy") as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("book_table", {"date": "Friday"})
    assert exc_info.value.error == ErrorData(code=INVALID_REQUEST, message="Elicitation not supported")


async def test_ctx_elicit_over_stateless_http_has_no_back_channel() -> None:
    """tutorial008: `stateless_http=True` leaves the server no channel to send `elicitation/create`."""
    transport = httpx.ASGITransport(app=tutorial008.app)
    async with tutorial008.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=transport) as http_client:
            async with Client(streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http_client)) as c:
                with pytest.raises(MCPError) as exc_info:
                    await c.call_tool("book_table", {"date": "Friday"})
    assert exc_info.value.error == ErrorData(
        code=INVALID_REQUEST,
        message=(
            "Cannot send 'elicitation/create': "
            "this transport context has no back-channel for server-initiated requests."
        ),
    )


async def test_a_request_state_the_server_did_not_mint_is_rejected(caplog: pytest.LogCaptureFixture) -> None:
    """The wire message is deliberately frozen; the real reason goes only to the server log."""
    async with Client(tutorial001.mcp) as client:
        with caplog.at_level(logging.WARNING, logger="mcp.server.request_state"):
            with pytest.raises(MCPError) as exc_info:
                await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
    assert exc_info.value.error == ErrorData(
        code=INVALID_PARAMS, message="Invalid or expired requestState", data={"reason": "invalid_request_state"}
    )
    assert "requestState rejected on tools/call: malformed" in caplog.messages


async def test_a_short_request_state_key_is_rejected_at_construction() -> None:
    """`RequestStateSecurity(keys=[...])` refuses anything under 32 bytes and says how to make one."""
    with pytest.raises(ValueError) as exc_info:
        RequestStateSecurity(keys=[b"hunter2"])
    assert str(exc_info.value) == (
        "request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. "
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
    )
