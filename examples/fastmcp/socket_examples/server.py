"""
Socket transport server script.

This script demonstrates:
1. Creating a FastMCP server with socket transport
2. Connecting back to the client's socket using the provided port
3. Running the server until the connection is closed
4. Handling connection errors and encoding
5. Supporting command-line configuration

Usage:
    python server.py --name NAME [--host HOST] [--port PORT]

Note:
    This server is typically started by the client (client.py).
    Direct execution is mainly for testing purposes.
"""

import argparse
import logging
import os
import sys
from typing import Dict

from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def echo_tool(text: str) -> str:
    """
    A simple echo tool that returns the input text.

    Args:
        text: The text to echo back

    Returns:
        The same text that was provided
    """
    logger.info(f"Echo tool called with: {text}")
    return text


async def get_pid_tool() -> Dict[str, int]:
    """
    A tool that returns the server's process ID.

    Returns:
        Dict[str, int]: A dictionary containing the server's process ID
    """
    return {"pid": os.getpid()}


def main():
    """Parse arguments and run the server with socket transport."""
    parser = argparse.ArgumentParser(description="Socket transport server example")
    parser.add_argument("--host", default="127.0.0.1", help="Host to connect to")
    parser.add_argument("--port", type=int, required=True, help="Port to connect to")
    parser.add_argument("--name", default="Socket Server", help="Server name")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Set logging level from arguments
    logging.getLogger().setLevel(args.log_level)

    try:
        # Create FastMCP server with socket settings
        server = FastMCP(
            name=args.name,
            socket_host=args.host,
            socket_port=args.port,
        )

        # Add our tools
        server.add_tool(echo_tool)
        server.add_tool(get_pid_tool)

        logger.info(f"Starting server {args.name} with socket transport")
        logger.info(f"Will connect to client at {args.host}:{args.port}")

        try:
            # Use the socket transport
            server.run(transport="socket")
        except McpError as e:
            logger.error(f"MCP error: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Server error: {e}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Failed to create server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
