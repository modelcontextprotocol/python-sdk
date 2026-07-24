from mcp.server.mcpserver import Context, MCPServer
from mcp.server.subscriptions import SubscriptionBus

NOTES = {"todo": "buy milk"}


def make_server(bus: SubscriptionBus) -> MCPServer:
    """Every replica gets its own server object; all of them hold the same bus."""
    mcp = MCPServer("Notebook", subscriptions=bus)

    @mcp.resource("note://{name}")
    def note(name: str) -> str:
        """One note, by name."""
        return NOTES[name]

    @mcp.tool()
    async def edit_note(name: str, text: str, ctx: Context) -> str:
        """Replace a note's text."""
        NOTES[name] = text
        await ctx.notify_resource_updated(f"note://{name}")
        return "saved"

    return mcp
