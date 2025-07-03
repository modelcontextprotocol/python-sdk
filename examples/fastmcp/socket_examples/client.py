"""
Example of using socket transport with FastMCP.

This example demonstrates:
1. Creating a FastMCP server that uses socket transport
2. Creating a client that connects to the server using socket transport
3. Exchanging messages between client and server
4. Handling connection errors and retries
5. Using custom encoding and configuration
6. Verifying server process cleanup

Usage:
    python client.py [--host HOST] [--port PORT] [--log-level LEVEL]
"""

import argparse
import asyncio
import logging
import sys
import psutil
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.socket_transport import SocketServerParameters, socket_client
from mcp.shared.exceptions import McpError

# Set up logging
logger = logging.getLogger(__name__)


async def verify_process_cleanup(pid: int) -> bool:
    """
    Verify if a process with given PID exists.

    Args:
        pid: Process ID to check

    Returns:
        bool: True if process does not exist (cleaned up), False if still running
    """
    try:
        process = psutil.Process(pid)
        return False  # Process still exists
    except psutil.NoSuchProcess:
        return True  # Process has been cleaned up


async def main(host: str = "127.0.0.1", port: int = 0, log_level: str = "INFO"):
    """
    Run the client which will start and connect to the server.

    Args:
        host: The host to use for socket communication (default: 127.0.0.1)
        port: The port to use for socket communication (default: 0 for auto-assign)
        log_level: Logging level (default: INFO)
    """
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    server_pid = None
    try:
        # Create server parameters with custom configuration
        params = SocketServerParameters(
            # The command to run the server
            command=sys.executable,  # Use current Python interpreter
            # Arguments to start the server script
            args=[
                str(Path(__file__).parent / "server.py"),  # Updated path
                "--name",
                "Echo Server",
                "--host",
                host,
                "--port",
                str(port),
                "--log-level",
                log_level,
            ],
            # Socket configuration
            host=host,
            port=port,
            # Optional: customize encoding (defaults shown)
            encoding="utf-8",
            encoding_error_handler="strict",
        )

        # Connect to server (this will start the server process)
        async with socket_client(params) as (read_stream, write_stream):
            # Create client session
            async with ClientSession(read_stream, write_stream) as session:
                try:
                    # Initialize the session
                    await session.initialize()
                    logger.info("Session initialized successfully")

                    # Get server process PID for verification
                    result = await session.call_tool("get_pid_tool", {})
                    server_pid = result.structuredContent["result"]["pid"]
                    logger.info(f"Server process PID: {server_pid}")

                    # List available tools
                    tools = await session.list_tools()
                    logger.info(f"Available tools: {[t.name for t in tools.tools]}")

                    # Call the echo tool with different inputs
                    messages = [
                        "Hello from socket transport!",
                        "Testing special chars: 世界, мир, ♥",
                        "Testing long message: " + "x" * 1000,
                    ]

                    for msg in messages:
                        try:
                            result = await session.call_tool("echo_tool", {"text": msg})
                            logger.info(f"Echo result: {result}")
                        except McpError as e:
                            logger.error(f"Tool call failed: {e}")

                except McpError as e:
                    logger.error(f"Session error: {e}")
                    sys.exit(1)

        # After session ends, verify server process cleanup
        if server_pid:
            await asyncio.sleep(0.5)  # Give some time for cleanup
            is_cleaned = await verify_process_cleanup(server_pid)
            if is_cleaned:
                logger.info(
                    f"Server process (PID: {server_pid}) was successfully cleaned up"
                )
            else:
                logger.warning(f"Server process (PID: {server_pid}) is still running!")

    except Exception as e:
        logger.error(f"Connection failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Socket transport example client")
    parser.add_argument("--host", default="127.0.0.1", help="Host to use")
    parser.add_argument("--port", type=int, default=0, help="Port to use (0 for auto)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Run everything
    asyncio.run(main(host=args.host, port=args.port, log_level=args.log_level))
