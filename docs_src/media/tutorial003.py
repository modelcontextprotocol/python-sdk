from mcp_types import Icon

from mcp.server import MCPServer

LOGO = Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])
PALETTE = Icon(src="https://example.com/palette.svg", mime_type="image/svg+xml", sizes=["any"])

mcp = MCPServer("Brand kit", icons=[LOGO])


@mcp.tool(icons=[PALETTE])
def palette() -> list[str]:
    """The brand colour palette as hex codes."""
    return ["#1d4ed8", "#f59e0b", "#10b981"]


@mcp.resource("brand://guidelines", icons=[LOGO])
def guidelines() -> str:
    """How to use the brand assets."""
    return "Use the primary colour for calls to action."
