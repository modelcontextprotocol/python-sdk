import base64

from mcp.server import MCPServer
from mcp.server.mcpserver import Audio, Image

mcp = MCPServer("Brand kit")

LOGO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQ9bsBAAHPAURf8l/aAAAAAElFTkSuQmCC"
)

CHIME_WAV = base64.b64decode("UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YRAAAAAAAAAAAAAAAAAAAAAAAAAA")


@mcp.tool()
def logo() -> Image:
    """The brand logo as a PNG."""
    return Image(data=LOGO_PNG, format="png")


@mcp.tool()
def chime() -> Audio:
    """The notification chime as a WAV."""
    return Audio(data=CHIME_WAV, format="wav")
