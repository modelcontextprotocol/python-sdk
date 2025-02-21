import pytest

import os
import sys
from .mcp_stdio_client import MCPClient

from mcp import StdioServerParameters

# locate the exmaple MCP server co-located in this directory

mcp_server_dir = os.path.dirname(os.path.abspath(__file__))
mcp_server_file = os.path.join(mcp_server_dir, "example_mcp_server.py")
                           
# mcpServers config in same syntax used by reference MCP

servers_config = {
    "mcpServers": {

        "testMcpServer": {
            "command": "mcp",   # be sure to . .venv/bin/activate so that mcp command is found
            "args": [
                "run",
                mcp_server_file
            ]
        }

    }
}


@pytest.mark.anyio
async def test_mcp():

    servers = servers_config.get("mcpServers")

    server0 = "testMcpServer"
    config0 = servers[server0]
    
    client = MCPClient(
        server0,
        StdioServerParameters.model_validate(config0)
    )
    await client.initialize()
    tools = await client.get_available_tools()

    print(f"TOOLS:{tools}")
    mcp_tool = tools[0]

    res = await client.call_tool("simple_tool", {"x":5, "y":7})

    print(f"RES:{res}")

    # clients must be destroyed in reverse order
    await client.cleanup()


@pytest.mark.anyio
async def test_mcp_with_logging():

    servers = servers_config.get("mcpServers")

    server0 = "testMcpServer"
    config0 = servers[server0]
    
    client = MCPClient(
        server0,
        StdioServerParameters.model_validate(config0)
    )
    await client.initialize()
    tools = await client.get_available_tools()

    print(f"TOOLS:{tools}")
    mcp_tool = tools[0]

    res = await client.call_tool("simple_tool_with_logging", {"x":5, "y":7})

    print(f"RES:{res}")

    # clients must be destroyed in reverse order
    await client.cleanup()
    
