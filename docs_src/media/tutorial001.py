import base64

from mcp.server import MCPServer
from mcp.server.mcpserver import Image

mcp = MCPServer("Brand kit")

LOGO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQ9bsBAAHPAURf8l/aAAAAAElFTkSuQmCC"
)


@mcp.tool()
def logo() -> Image:
    """The brand logo as a PNG."""
    return Image(data=LOGO_PNG, format="png")
