"""
cd to the `examples/snippets` directory and run:
    uv run display-utilities-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.metadata_utils import get_display_name

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",  # Using uv to run the server
    args=["run", "server", "fastmcp_quickstart", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def display_tools(session: ClientSession):
    """Display available tools with human-readable names"""
    tools_response = await session.list_tools()

    for tool in tools_response.tools:
        # get_display_name() returns the title if available, otherwise the name
        display_name = get_display_name(tool)
        print(f"Tool: {display_name}")
        if tool.description:
            print(f"   {tool.description}")


async def display_resources(session: ClientSession):
    """Display available resources with human-readable names"""
    resources_response = await session.list_resources()

    for resource in resources_response.resources:
        display_name = get_display_name(resource)
        print(f"Resource: {display_name} ({resource.uri})")

    templates_response = await session.list_resource_templates()
    for template in templates_response.resourceTemplates:
        display_name = get_display_name(template)
        print(f"Resource Template: {display_name}")


async def run():
    """Run the display utilities example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            print("=== Available Tools ===")
            await display_tools(session)

            print("\n=== Available Resources ===")
            await display_resources(session)


def main():
    """Entry point for the display utilities client."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
