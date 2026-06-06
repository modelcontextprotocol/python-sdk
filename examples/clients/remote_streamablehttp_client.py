"""
Remote MCP Server Client Example — TWZRD Agent Intel
=====================================================

This example shows how to connect to a remote MCP server using
streamable-http transport, which is the recommended transport for
production/hosted MCP servers.

TWZRD Agent Intel (https://intel.twzrd.xyz) is a live production MCP server
providing trust scoring for Web3 AI agents. It accepts the standard MCP
streamable-http transport with no authentication required for free tools.

MCP config (for Claude Desktop / claude_desktop_config.json):
  {
    "mcpServers": {
      "twzrd-agent-intel": {
        "url": "https://intel.twzrd.xyz/mcp"
      }
    }
  }

Install:
  pip install mcp

This example demonstrates:
  - Connecting to a remote MCP server via streamable-http
  - Calling tools on the remote server
  - Handling tool results
"""
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Live production MCP server — no authentication required for free tools
SERVER_URL = "https://intel.twzrd.xyz/mcp"

# Example Web3 agent wallet address
EXAMPLE_WALLET = "D1QkbFJKiPsymJ65RKHhF6DFB8sPMfpBaFBzuHKfJGWi"


async def main() -> None:
    print(f"Connecting to remote MCP server: {SERVER_URL}")
    print("-" * 50)

    async with streamablehttp_client(SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            init_result = await session.initialize()
            print(f"Server: {init_result.serverInfo.name} v{init_result.serverInfo.version}")
            print()

            # List available tools
            tools_result = await session.list_tools()
            print(f"Available tools ({len(tools_result.tools)}):")
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description}")
            print()

            # Call the score_agent tool (free, no payment required)
            print(f"Calling score_agent for wallet: {EXAMPLE_WALLET}")
            score_result = await session.call_tool(
                "score_agent",
                arguments={"wallet": EXAMPLE_WALLET},
            )
            print("Score result:")
            for content_item in score_result.content:
                print(f"  {content_item.text}")
            print()

            # Call the preflight_check tool (free, no payment required)
            print(f"Calling preflight_check for wallet: {EXAMPLE_WALLET}")
            preflight_result = await session.call_tool(
                "preflight_check",
                arguments={"wallet": EXAMPLE_WALLET},
            )
            print("Preflight result:")
            for content_item in preflight_result.content:
                print(f"  {content_item.text}")


if __name__ == "__main__":
    asyncio.run(main())
