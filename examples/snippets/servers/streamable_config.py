"""
Run from the repository root:
    uv run examples/snippets/servers/streamable_config.py
"""

from mcp.server.fastmcp import FastMCP

# Stateless server with JSON responses (recommended)
mcp = FastMCP("StatelessServer", stateless_http=True, json_response=True)

# Other configuration options:
# Stateless server with SSE streaming responses
# mcp = FastMCP("StatelessServer", stateless_http=True)

# Stateful server with session persistence
# mcp = FastMCP("StatefulServer")


# Add a simple tool to demonstrate the server
@mcp.tool()
def greet(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


# Run server with streamable_http transport
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
