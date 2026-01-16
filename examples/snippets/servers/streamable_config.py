"""
Run from the repository root:
    uv run examples/snippets/servers/streamable_config.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("StatelessServer")


# Add a simple tool to demonstrate the server
@mcp.tool()
def greet(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


# Run server with streamable_http transport
# Transport-specific options (stateless_http, json_response) are passed to run()
if __name__ == "__main__":
    # Stateless server with JSON responses (recommended)
    mcp.run(transport="streamable-http", stateless_http=True, json_response=True)

    # Other configuration options:
    # Stateless server with SSE streaming responses
    # mcp.run(transport="streamable-http", stateless_http=True)

    # Stateful server with session persistence
    # mcp.run(transport="streamable-http")
