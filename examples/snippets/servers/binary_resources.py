from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Binary Resource Example")


@mcp.resource("images://logo.png", mime_type="image/png")
def get_logo() -> bytes:
    """Return a binary image resource."""
    with open("logo.png", "rb") as f:
        return f.read()
