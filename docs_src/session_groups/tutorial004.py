import asyncio

from mcp_types import Implementation

from mcp import ClientSessionGroup, StdioServerParameters


def by_server(name: str, server_info: Implementation) -> str:
    return f"{server_info.name}.{name}"


async def main() -> None:
    library = StdioServerParameters(command="uv", args=["run", "mcp", "run", "library_server.py"])
    web = StdioServerParameters(command="uv", args=["run", "mcp", "run", "web_server.py"])

    async with ClientSessionGroup(component_name_hook=by_server) as group:
        await group.connect_to_server(library)
        await group.connect_to_server(web)

        print(sorted(group.tools))
        result = await group.call_tool("Web.search", {"query": "model context protocol"})
        print(result.structured_content)


if __name__ == "__main__":
    asyncio.run(main())
