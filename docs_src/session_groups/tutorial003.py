import asyncio

from mcp import ClientSessionGroup, StdioServerParameters


async def main() -> None:
    library = StdioServerParameters(command="uv", args=["run", "mcp", "run", "library_server.py"])
    web = StdioServerParameters(command="uv", args=["run", "mcp", "run", "web_server.py"])

    async with ClientSessionGroup() as group:
        await group.connect_to_server(library)
        await group.connect_to_server(web)

        result = await group.call_tool("search", {"query": "model context protocol"})
        print(result.structured_content)


if __name__ == "__main__":
    asyncio.run(main())
