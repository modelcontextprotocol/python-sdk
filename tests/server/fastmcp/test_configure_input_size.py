"""Test that the maximum http input size is configurable via FastMCP settings"""

import pytest

from mcp.server.fastmcp import FastMCP


@pytest.mark.anyio
async def test_configure_input_size():
    """Create a FastMCP server with StreamableHTTP transport."""
    configured_input_size = 1024
    mcp = FastMCP("Test Server", maximum_message_size=configured_input_size)

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the StreamableHTTP app
    _ = mcp.streamable_http_app()

    # Check that the maximum input size is set correctly
    assert mcp.session_manager.maximum_message_size == configured_input_size
