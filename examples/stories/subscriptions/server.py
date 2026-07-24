"""A notebook whose edits and tool changes reach `subscriptions/listen` streams."""

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("subscriptions-example")
    notes = {"todo": "buy milk", "journal": "day one"}

    @mcp.resource("note://{name}")
    def note(name: str) -> str:
        return notes[name]

    @mcp.tool()
    async def edit_note(name: str, text: str, ctx: Context) -> str:
        """Replace a note's text and tell subscribers that URI changed."""
        notes[name] = text
        await ctx.notify_resource_updated(f"note://{name}")
        return "saved"

    def search(query: str) -> list[str]:
        return [name for name, text in notes.items() if query in text]

    enabled = False

    @mcp.tool()
    async def enable_search(ctx: Context) -> str:
        """Register the `search` tool at runtime and tell subscribers the list changed."""
        nonlocal enabled
        if not enabled:
            enabled = True
            mcp.add_tool(search)
            await ctx.notify_tools_changed()
        return "search is live"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
