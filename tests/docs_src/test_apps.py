"""`docs/advanced/apps.md`: every claim the page makes, proved against the real SDK."""

from typing import Any

import pytest
from mcp_types import TextContent, TextResourceContents

from docs_src.apps import tutorial001, tutorial002
from mcp import Client
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_tool_carries_the_ui_resource_reference() -> None:
    """tutorial001: `@apps.tool(resource_uri=...)` stamps `_meta.ui.resourceUri` on the tool."""
    async with Client(tutorial001.mcp) as client:
        listed = await client.list_tools()
    assert listed.tools[0].meta == {"ui": {"resourceUri": "ui://clock/app.html"}}


async def test_the_ui_resource_is_served_as_the_app_mime_type() -> None:
    """tutorial001: `add_html_resource` serves the HTML at `text/html;profile=mcp-app`,
    the MIME type that tells a host "this is an app, render it"."""
    async with Client(tutorial001.mcp) as client:
        result = await client.read_resource("ui://clock/app.html")
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.mime_type == APP_MIME_TYPE
    assert contents.text == tutorial001.CLOCK_HTML


async def test_one_tool_two_answers() -> None:
    """tutorial001: the canonical degradation pattern: raw data for a client that
    negotiated Apps, a human sentence for one that did not."""
    async with Client(tutorial001.mcp, extensions={EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}) as ui_client:
        rich = await ui_client.call_tool("get_time", {})
    async with Client(tutorial001.mcp) as text_client:
        plain = await text_client.call_tool("get_time", {})
    assert rich.content == [TextContent(type="text", text="2026-06-26T12:00:00Z")]
    assert plain.content == [TextContent(type="text", text="The time is 2026-06-26T12:00:00Z.")]


async def test_capability_advertised_under_server_extensions() -> None:
    """tutorial001: passing `extensions=[apps]` advertises `io.modelcontextprotocol/ui`."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_capabilities.extensions == {EXTENSION_ID: {}}


async def test_csp_permissions_domain_and_border_ride_the_resource_meta() -> None:
    """tutorial002: the iframe lockdown fields land under `_meta.ui` on both the list
    entry and the read content item, with the spec's camelCase wire keys."""
    expected: dict[str, Any] = {
        "ui": {
            "csp": {"connectDomains": ["https://api.example.com"]},
            "permissions": {"clipboardWrite": {}},
            "domain": "dashboard.example.com",
            "prefersBorder": True,
        }
    }
    async with Client(tutorial002.mcp) as client:
        listed = await client.list_resources()
        result = await client.read_resource("ui://dashboard/app.html")
    assert listed.resources[0].meta == expected
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.meta == expected


async def test_an_app_only_tool_is_still_listed_and_callable() -> None:
    """tutorial002: `visibility=["app"]` is metadata for the host; the server lists the
    tool like any other and serves its calls; filtering is the host's job."""
    async with Client(tutorial002.mcp) as client:
        listed = await client.list_tools()
        result = await client.call_tool("refresh_dashboard", {})
    assert listed.tools[0].meta == {"ui": {"resourceUri": "ui://dashboard/app.html", "visibility": ["app"]}}
    assert result.content == [TextContent(type="text", text="refreshed")]
