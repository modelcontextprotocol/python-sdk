from mcp import Client
from mcp.client import TasksExtension
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import Tasks

mcp = MCPServer("bakery", extensions=[Tasks()])


@mcp.tool()
def bake(flavor: str) -> str:
    """Bake a cake."""
    return f"One {flavor} cake, ready."


async def main() -> None:
    async with Client(mcp, extensions=[TasksExtension()]) as client:
        result = await client.call_tool("bake", {"flavor": "lemon"})
        print(result.content)
        # [TextContent(text='One lemon cake, ready.')]
