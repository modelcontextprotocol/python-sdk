from mcp.server import MCPServer

mcp = MCPServer("Notes")


@mcp.tool()
def add_note(text: str) -> str:
    """Save a note."""
    return f"Saved: {text}"


app = mcp.streamable_http_app()
