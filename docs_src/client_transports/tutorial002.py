from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.list_tools()
        print([tool.name for tool in result.tools])
