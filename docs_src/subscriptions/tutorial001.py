from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer("Notebook")

NOTES = {"todo": "buy milk", "journal": "day one"}


@mcp.resource("note://{name}")
def note(name: str) -> str:
    return NOTES[name]


@mcp.tool()
async def edit_note(name: str, text: str, ctx: Context) -> str:
    NOTES[name] = text
    await ctx.notify_resource_updated(f"note://{name}")
    return "saved"


def search(query: str) -> list[str]:
    return [name for name, text in NOTES.items() if query in text]


@mcp.tool()
async def enable_search(ctx: Context) -> str:
    mcp.add_tool(search)
    await ctx.notify_tools_changed()
    return "search is live"
