"""Roots primitive: a tool asks the client which filesystem roots it may use."""

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("roots-example")

    @mcp.tool(description="Return the filesystem roots the client has exposed.")
    async def show_roots(ctx: Context) -> str:
        result = await ctx.session.list_roots()  # pyright: ignore[reportDeprecated]
        return "\n".join(f"{root.uri} ({root.name or 'unnamed'})" for root in result.roots)

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
