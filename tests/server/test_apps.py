"""Tests for the MCP Apps extension (`io.modelcontextprotocol/ui`, SEP-2133).

The headline property is SEP-2133 graceful degradation: a UI-bound tool returns
rich output to a client that negotiated Apps and text-only output to one that did
not. The remaining tests pin SDK-defined wiring (the `_meta.ui.resourceUri` stamp,
the `ui://` resource MIME type, capability advertisement, and `ui://`-scheme
validation).
"""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, ReadResourceResult, TextContent, TextResourceContents

from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

pytestmark = pytest.mark.anyio


def _clock_server() -> MCPServer:
    apps = Apps()

    @apps.tool(resource_uri="ui://clock/app.html", title="Get Time", description="Return the current time.")
    def get_time(ctx: Context) -> str:
        if not client_supports_apps(ctx):
            return "The time is 2026-06-26T00:00:00Z."
        return "2026-06-26T00:00:00Z"

    apps.add_html_resource("ui://clock/app.html", "<title>Clock</title>", title="Clock")
    return MCPServer("clock", extensions=[apps])


async def test_apps_tool_stamps_ui_resource_uri_on_tool_meta() -> None:
    """SDK-defined: `@apps.tool(resource_uri=...)` stamps `_meta.ui.resourceUri` on the
    advertised tool, observed end-to-end through `list_tools`."""
    async with Client(_clock_server()) as client:
        result = await client.list_tools()
    assert [(t.name, t.meta) for t in result.tools] == snapshot(
        [("get_time", {"ui": {"resourceUri": "ui://clock/app.html"}})]
    )


async def test_add_html_resource_serves_ui_resource_at_app_mime_type() -> None:
    """SDK-defined: `add_html_resource` registers the `ui://` resource served as
    `text/html;profile=mcp-app`, observed through `read_resource`."""
    async with Client(_clock_server()) as client:
        result = await client.read_resource("ui://clock/app.html")
    assert result == snapshot(
        ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri="ui://clock/app.html",
                    mime_type="text/html;profile=mcp-app",
                    text="<title>Clock</title>",
                )
            ]
        )
    )
    assert isinstance(result.contents[0], TextResourceContents)
    assert result.contents[0].mime_type == APP_MIME_TYPE


async def test_auto_mode_carries_apps_extension_under_server_capabilities() -> None:
    """SDK-defined: the Apps extension rides `server/discover`, so a `mode='auto'` client
    sees `EXTENSION_ID` under `server_capabilities.extensions`."""
    async with Client(_clock_server(), mode="auto") as client:
        assert client.server_capabilities.extensions == snapshot({"io.modelcontextprotocol/ui": {}})


async def test_legacy_handshake_drops_apps_extension_from_capabilities() -> None:
    """Pinned gap: the 2025 `ServerCapabilities` wire schema has no `extensions` field,
    so a `mode='legacy'` handshake cannot carry the Apps capability -- only `mode='auto'`
    (server/discover) does. This pins the divergence rather than fixing it."""
    async with Client(_clock_server(), mode="legacy") as client:
        assert client.server_capabilities.extensions is None


async def test_apps_tool_returns_rich_output_when_client_negotiated_apps() -> None:
    """SEP-2133 graceful degradation: a client that advertised `EXTENSION_ID` gets the
    rich (UI) path, while one that did not gets the text-only fallback. The same tool,
    branching on `client_supports_apps(ctx)`, drives both halves."""
    server = _clock_server()

    async with Client(server, extensions={EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}) as supports:
        rich = await supports.call_tool("get_time", {})
    async with Client(server) as plain:
        fallback = await plain.call_tool("get_time", {})

    assert rich.content == snapshot([TextContent(text="2026-06-26T00:00:00Z")])
    assert fallback.content == snapshot([TextContent(text="The time is 2026-06-26T00:00:00Z.")])


async def test_client_supports_apps_reads_lowlevel_request_context() -> None:
    """SDK-defined: `client_supports_apps` accepts a lowlevel `ServerRequestContext` too,
    reading the client's advertised extensions off `session.client_params`."""
    observed: list[bool] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="probe", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "probe"
        observed.append(client_supports_apps(ctx))
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("probe", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server, extensions={EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}) as supports:
        await supports.call_tool("probe", {})
    async with Client(server) as plain:
        await plain.call_tool("probe", {})

    assert observed == [True, False]


def test_apps_tool_rejects_non_ui_resource_uri() -> None:
    """SDK-defined: `@apps.tool` accepts only `ui://` URIs; any other scheme is a
    programmer error raised at decoration time."""
    apps = Apps()
    with pytest.raises(ValueError):
        apps.tool(resource_uri="https://example.com/app.html")


def test_add_html_resource_rejects_non_ui_resource_uri() -> None:
    """SDK-defined: `add_html_resource` accepts only `ui://` URIs; any other scheme is
    a programmer error raised at registration time."""
    apps = Apps()
    with pytest.raises(ValueError):
        apps.add_html_resource("https://example.com/app.html", "<title>x</title>")
