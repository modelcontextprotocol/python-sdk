import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    try:
        print("Starting MCP Client...")
        server_params = StdioServerParameters(
            command="python",
            args=["example_server.py"],
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("Connected to MCP server via stdio.")

                prompts = await session.list_prompts()
                print(f"Available prompts: {[p.name for p in prompts]}")

                resources = await session.list_resources()
                resource_list = [
                    str(r.uri) if hasattr(r, "uri") else str(r) for r in resources
                ]
                print(f"Available resources: {resource_list}")

                tools = await session.list_tools()
                print(f"Available tools: {[t.name for t in tools]}")

                if tools:
                    tool_name = tools[0].name
                    print(f"Calling tool: {tool_name}")
                    result = await session.call_tool(
                        tool_name, arguments={"a": 5, "b": 3}
                    )
                    print(f"Tool result: {result}")
    except Exception as e:
        print(f"Error during client operation: {e}")


if __name__ == "__main__":
    asyncio.run(main())
