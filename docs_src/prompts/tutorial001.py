from mcp.server import MCPServer

mcp = MCPServer("Code Helper")


@mcp.prompt()
def review_code(code: str) -> str:
    """Review a piece of code."""
    return f"Please review this code:\n\n{code}"
