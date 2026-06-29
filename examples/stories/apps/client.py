"""Negotiate MCP Apps, discover a tool's `ui://` UI, fetch it, and call the tool."""

from mcp_types import TextContent, TextResourceContents

from mcp.client import Client
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    # Advertise MCP Apps support so the server returns the UI-enabled result; a
    # client that omits this gets the text-only fallback (graceful degradation).
    async with Client(target, mode=mode, extensions={EXTENSION_ID: {"mimeTypes": [APP_MIME_TYPE]}}) as client:
        # The extensions capability map rides `server/discover` (modern only). On a
        # legacy connection (today's stdio) it is absent, so assert it only when present.
        if client.server_capabilities.extensions is not None:
            assert client.server_capabilities.extensions == {EXTENSION_ID: {}}, client.server_capabilities.extensions

        listed = await client.list_tools()
        tool = next(t for t in listed.tools if t.name == "get_time")
        assert tool.meta is not None, tool
        assert tool.meta["ui"]["resourceUri"] == "ui://get-time/app.html", tool.meta

        ui = await client.read_resource("ui://get-time/app.html")
        contents = ui.contents[0]
        assert isinstance(contents, TextResourceContents)
        assert contents.mime_type == APP_MIME_TYPE, contents.mime_type

        result = await client.call_tool("get_time", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "2026-06-26T00:00:00Z", result.content[0].text


if __name__ == "__main__":
    run_client(main)
