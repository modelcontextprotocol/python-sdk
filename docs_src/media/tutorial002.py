from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Audio, Image

mcp = MCPServer("Brand kit")

LOGO_FILE = Path(__file__).parent / "logo.png"
CHIME_FILE = Path(__file__).parent / "chime.wav"


@mcp.tool()
def logo() -> Image:
    """The brand logo as a PNG."""
    return Image(path=LOGO_FILE)


@mcp.tool()
def chime() -> Audio:
    """The notification chime as a WAV."""
    return Audio(path=CHIME_FILE)
