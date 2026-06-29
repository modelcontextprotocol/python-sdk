"""Sessionful Streamable HTTP: a tool mutates resources and emits `list_changed` over the standalone GET stream."""

import itertools

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.resources import TextResource
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("standalone-get-example")
    counter = itertools.count(1)

    mcp.add_resource(TextResource(uri="note://initial", name="initial", text="initial content"))

    @mcp.tool()
    async def add_note(content: str, ctx: Context) -> str:
        """Register a new resource and announce it via `notifications/resources/list_changed`."""
        name = f"note-{next(counter)}"
        mcp.add_resource(TextResource(uri=f"note://{name}", name=name, text=content))
        # Not auto-emitted on add_resource; with no related_request_id this routes to the standalone GET stream.
        await ctx.session.send_resource_list_changed()
        return f"registered {name}"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
