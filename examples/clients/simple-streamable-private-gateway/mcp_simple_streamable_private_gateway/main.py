#!/usr/bin/env python3
"""
Simple MCP streamable private gateway client example without authentication.

This client connects to an MCP server using streamable HTTP or SSE transport
with custom extensions for private gateway connectivity (SNI hostname support).

"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.message import SessionMessage


class SimpleStreamablePrivateGateway:
    """Simple MCP private gateway client supporting StreamableHTTP and SSE transports.
    
    This client demonstrates how to use custom extensions (e.g., SNI hostname) for
    private gateway connectivity with both transport types.
    """

    def __init__(self, server_url: str, server_hostname: str, transport_type: str = "streamable-http"):
        self.server_url = server_url
        self.server_hostname = server_hostname
        self.transport_type = transport_type
        self.session: ClientSession | None = None

    async def connect(self):
        """Connect to the MCP server."""
        print(f"🔗 Attempting to connect to {self.server_url}...")

        try:
            # Create transport based on transport type
            if self.transport_type == "sse":
                print("📡 Opening SSE transport connection with extensions...")
                # SSE transport with custom extensions for private gateway
                async with sse_client(
                    url=self.server_url,
                    headers={"Host": self.server_hostname},
                    extensions={"sni_hostname": self.server_hostname},
                    timeout=60,
                ) as (read_stream, write_stream):
                    await self._run_session(read_stream, write_stream, None)
            else:
                print("📡 Opening StreamableHTTP transport connection with extensions...")
                # Note: terminate_on_close=False prevents SSL handshake failures during exit
                # Some servers may not handle session termination gracefully over SSL
                async with streamablehttp_client(
                    url=self.server_url,
                    headers={"Host": self.server_hostname},
                    extensions={"sni_hostname": self.server_hostname},
                    timeout=timedelta(seconds=60),
                    terminate_on_close=False,  # Skip session termination to avoid SSL errors
                ) as (read_stream, write_stream, get_session_id):
                    await self._run_session(read_stream, write_stream, get_session_id)

        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            import traceback

            traceback.print_exc()

    async def _run_session(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        get_session_id: Callable[[], str | None] | None,
    ):
        """Run the MCP session with the given streams."""
        print("🤝 Initializing MCP session...")
        async with ClientSession(read_stream, write_stream) as session:
            self.session = session
            print("⚡ Starting session initialization...")
            await session.initialize()
            print("✨ Session initialization complete!")

            print(f"\n✅ Connected to MCP server at {self.server_url}")
            if get_session_id:
                session_id = get_session_id()
                if session_id:
                    print(f"Session ID: {session_id}")

            # Run interactive loop
            await self.interactive_loop()

    async def list_tools(self):
        """List available tools from the server."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.list_tools()
            if hasattr(result, "tools") and result.tools:
                print("\n📋 Available tools:")
                for i, tool in enumerate(result.tools, 1):
                    print(f"{i}. {tool.name}")
                    if tool.description:
                        print(f"   Description: {tool.description}")
                    print()
            else:
                print("No tools available")
        except Exception as e:
            print(f"❌ Failed to list tools: {e}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None):
        """Call a specific tool."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.call_tool(tool_name, arguments or {})
            print(f"\n🔧 Tool '{tool_name}' result:")
            if hasattr(result, "content"):
                for content in result.content:
                    if content.type == "text":
                        print(content.text)
                    else:
                        print(content)
            else:
                print(result)
        except Exception as e:
            print(f"❌ Failed to call tool '{tool_name}': {e}")

    async def interactive_loop(self):
        """Run interactive command loop."""
        print("\n🎯 Interactive MCP Client (Private Gateway)")
        print("Commands:")
        print("  list - List available tools")
        print("  call <tool_name> [args] - Call a tool")
        print("  quit - Exit the client")
        print()

        while True:
            try:
                command = input("mcp> ").strip()

                if not command:
                    continue

                if command == "quit":
                    print("👋 Goodbye!")
                    break

                elif command == "list":
                    await self.list_tools()

                elif command.startswith("call "):
                    parts = command.split(maxsplit=2)
                    tool_name = parts[1] if len(parts) > 1 else ""

                    if not tool_name:
                        print("❌ Please specify a tool name")
                        continue

                    # Parse arguments (simple JSON-like format)
                    arguments = {}
                    if len(parts) > 2:
                        import json

                        try:
                            arguments = json.loads(parts[2])
                        except json.JSONDecodeError:
                            print("❌ Invalid arguments format (expected JSON)")
                            continue

                    await self.call_tool(tool_name, arguments)

                else:
                    print("❌ Unknown command. Try 'list', 'call <tool_name>', or 'quit'")

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except EOFError:
                print("\n👋 Goodbye!")
                break


def get_user_input():
    """Get server configuration from user input."""
    print("🚀 Simple Streamable Private Gateway")
    print("\n📝 Server Configuration")
    print("=" * 50)
    
    # Get server port
    server_port = input("Server port [8081]: ").strip() or "8081"
    
    # Get server hostname
    server_hostname = input("Server hostname [mcp.deepwiki.com]: ").strip() or "mcp.deepwiki.com"
    
    # Get transport type
    print("\nTransport type:")
    print("  1. streamable-http (default)")
    print("  2. sse")
    transport_choice = input("Select transport [1]: ").strip() or "1"
    
    if transport_choice == "2":
        transport_type = "sse"
    else:
        transport_type = "streamable-http"
    
    print("=" * 50)
    
    return server_port, server_hostname, transport_type


async def main():
    """Main entry point."""
    try:
        # Get configuration from user input
        server_port, server_hostname, transport_type = get_user_input()
        
        # Set URL endpoint based on transport type
        # StreamableHTTP servers typically use /mcp, SSE servers use /sse
        endpoint = "/mcp" if transport_type == "streamable-http" else "/sse"
        server_url = f"https://localhost:{server_port}{endpoint}"

        print(f"\n🔗 Connecting to: {server_url}")
        print(f"📡 Server hostname: {server_hostname}")
        print(f"🚀 Transport type: {transport_type}\n")

        # Start connection flow
        client = SimpleStreamablePrivateGateway(server_url, server_hostname, transport_type)
        await client.connect()
        
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except EOFError:
        print("\n👋 Goodbye!")


def cli():
    """CLI entry point for uv script."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
