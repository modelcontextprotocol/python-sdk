import asyncio

from anyio.abc import Process

from mcp.client.stdio import stdio_client
from mcp.client.stdio.win32 import (
    create_windows_process,
    get_windows_executable_command,
    terminate_windows_process,
)


async def run_mcp_client():
    # Prepare the command to run the MCP server (assuming MCP server is already running)
    command = get_windows_executable_command("python")
    args = ["mcp_server.py"]
    process: Process = await create_windows_process(command, args)

    try:
        print("Connecting to MCP server using stdio...")

        # Using stdio_client for communication
        async with stdio_client(server={"command": command, "args": args}) as client:
            print("Connected to MCP server!")

            # List available tools
            tools = await client.list_tools()
            print(f"Available tools: {tools}")

            # Call the 'add' tool with two integers
            result = await client.call_tool("add", {"a": 5, "b": 3})
            print(f"Result from 'add' tool: {result}")

    except Exception as e:
        print(f"Error during client operation: {e}")
    finally:
        # Gracefully terminate the process
        print("Terminating the MCP server process...")
        await terminate_windows_process(process)


if __name__ == "__main__":
    asyncio.run(run_mcp_client())
