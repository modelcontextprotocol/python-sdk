from mcp import Client, StdioServerParameters

server = StdioServerParameters(
    command="uv",
    args=["run", "server.py"],
    env={"BOOKSHOP_API_KEY": "secret"},
)


async def main() -> None:
    async with Client(server) as client:
        result = await client.list_tools()
        print([tool.name for tool in result.tools])
