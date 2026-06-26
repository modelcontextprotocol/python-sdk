from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

server = StdioServerParameters(
    command="uv",
    args=["run", "server.py"],
    env={"BOOKSHOP_API_KEY": "secret"},
)


async def main() -> None:
    async with Client(stdio_client(server)) as client:
        result = await client.list_tools()
        print([tool.name for tool in result.tools])
