"""Tests for the MCP Apps extension (`io.modelcontextprotocol/ui`, SEP-2133).

The headline property is SEP-2133 graceful degradation: a UI-bound tool returns
rich output to a client that negotiated Apps and text-only output to one that did
not. The remaining tests pin SDK-defined wiring (the `_meta.ui.resourceUri` stamp,
the `ui://` resource MIME type, capability advertisement, and `ui://`-scheme
validation).
"""

from typing import Any

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, ReadResourceResult, TextContent, TextResourceContents

from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.apps import (
    APP_MIME_TYPE,
    EXTENSION_ID,
    Apps,
    ResourceCsp,
    ResourcePermissions,
    client_supports_apps,
)
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.resources import TextResource

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


async def _observed_client_supports_apps(extensions: dict[str, dict[str, Any]] | None) -> bool:
    """Run one probe `tools/call` and report what `client_supports_apps` saw server-side.

    Exercises the lowlevel `ServerRequestContext` form, which reads the client's
    advertised extensions off `session.client_params`.
    """
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
    async with Client(server, extensions=extensions) as client:
        await client.call_tool("probe", {})
    return observed[0]


@pytest.mark.parametrize(
    ("extensions", "expected"),
    [
        pytest.param({EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}, True, id="html-mime-listed"),
        pytest.param({EXTENSION_ID: {"mimeTypes": (APP_MIME_TYPE,)}}, True, id="in-process-tuple-mime-types"),
        pytest.param(None, False, id="extension-not-declared"),
        pytest.param({EXTENSION_ID: {"mimeTypes": ["application/x-other"]}}, False, id="html-mime-not-offered"),
        pytest.param({EXTENSION_ID: {}}, False, id="mime-types-key-missing"),
    ],
)
async def test_client_supports_apps_from_lowlevel_request_context(
    extensions: dict[str, dict[str, Any]] | None, expected: bool
) -> None:
    """ext-apps: `client_supports_apps` is `True` only when the client declared the ui
    extension AND listed `text/html;profile=mcp-app` in its `mimeTypes` settings — a
    required field, so its absence means unsupported (the reference SDK's check is
    `uiCap?.mimeTypes?.includes(...)`)."""
    assert await _observed_client_supports_apps(extensions) is expected


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


def _widget() -> str:
    """A UI-bound tool body (shared so its one covered call serves both meta tests)."""
    return "x"


async def test_apps_tool_stamps_visibility_when_given() -> None:
    """SDK-defined: `@apps.tool(visibility=...)` is stamped into `_meta.ui.visibility`."""
    apps = Apps()
    apps.tool(resource_uri="ui://v/app.html", visibility=["app"])(_widget)
    apps.add_html_resource("ui://v/app.html", "<title>v</title>")

    async with Client(MCPServer("v", extensions=[apps])) as client:
        result = await client.list_tools()
        called = await client.call_tool("_widget", {})

    assert result.tools[0].meta == snapshot({"ui": {"resourceUri": "ui://v/app.html", "visibility": ["app"]}})
    assert called.content == snapshot([TextContent(text="x")])


async def test_apps_tool_merges_extra_meta_alongside_ui() -> None:
    """SDK-defined: `@apps.tool(meta=...)` merges extra `_meta` keys with the `ui` entry
    (previously a `meta=` argument raised a duplicate-keyword TypeError)."""
    apps = Apps()
    apps.tool(resource_uri="ui://m/app.html", meta={"com.example/k": 1})(_widget)
    apps.add_html_resource("ui://m/app.html", "<title>m</title>")

    async with Client(MCPServer("m", extensions=[apps])) as client:
        result = await client.list_tools()

    assert result.tools[0].meta == snapshot({"com.example/k": 1, "ui": {"resourceUri": "ui://m/app.html"}})


async def test_add_html_resource_stamps_csp_and_permissions_on_resource_meta() -> None:
    """SDK-defined: `csp`/`permissions` populate the resource's `_meta.ui` per ext-apps."""
    apps = Apps()
    apps.add_html_resource(
        "ui://r/app.html",
        "<title>r</title>",
        csp=ResourceCsp(connect_domains=["https://api.example.com"]),
        permissions=ResourcePermissions(camera={}),
        domain="r.example.com",
        prefers_border=True,
    )

    async with Client(MCPServer("r", extensions=[apps])) as client:
        result = await client.read_resource("ui://r/app.html")

    assert isinstance(result.contents[0], TextResourceContents)
    assert result.contents[0].meta == snapshot(
        {
            "ui": {
                "csp": {"connectDomains": ["https://api.example.com"]},
                "permissions": {"camera": {}},
                "domain": "r.example.com",
                "prefersBorder": True,
            }
        }
    )


def test_apps_tool_with_unregistered_resource_uri_is_rejected_at_construction() -> None:
    """SDK-defined: a tool whose `resource_uri` has no matching registered resource would
    advertise a `_meta.ui.resourceUri` that 404s on `resources/read`; the misconfiguration
    is rejected when the server consumes the extension."""
    apps = Apps()
    apps.tool(resource_uri="ui://missing/app.html")(_widget)

    with pytest.raises(ValueError) as exc_info:
        MCPServer("broken", extensions=[apps])
    assert str(exc_info.value) == snapshot(
        "Apps tool '_widget' binds resource_uri 'ui://missing/app.html', but no such resource "
        "is registered; add it with add_html_resource() or add_resource()"
    )


async def test_add_resource_registers_a_prebuilt_ui_resource() -> None:
    """SDK-defined: `add_resource` is the escape hatch for pre-built `ui://` resources
    that `add_html_resource` cannot express; it satisfies a tool's `resource_uri` binding."""
    apps = Apps()
    apps.tool(resource_uri="ui://prebuilt/app.html")(_widget)
    apps.add_resource(
        TextResource(uri="ui://prebuilt/app.html", name="prebuilt", mime_type=APP_MIME_TYPE, text="<title>p</title>")
    )

    async with Client(MCPServer("p", extensions=[apps])) as client:
        result = await client.read_resource("ui://prebuilt/app.html")

    assert isinstance(result.contents[0], TextResourceContents)
    assert result.contents[0].text == "<title>p</title>"


def test_add_resource_rejects_non_ui_resource_uri() -> None:
    """SDK-defined: `add_resource` accepts only `ui://` URIs, like the other registrars."""
    apps = Apps()
    with pytest.raises(ValueError):
        apps.add_resource(TextResource(uri="https://example.com/app.html", name="x", text="x"))
