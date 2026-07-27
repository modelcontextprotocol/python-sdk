from mcp.server import MCPServer

mcp = MCPServer("Calculator")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
