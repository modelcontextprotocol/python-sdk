from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Image, Message, UserMessage

mcp = MCPServer("Code Helper")

DIAGRAM_FILE = Path(__file__).parent / "architecture.png"  # or the path to your file on disk


@mcp.prompt()
def explain_component(component: str) -> list[Message]:
    """Explain one component using the architecture diagram."""
    return [
        UserMessage(Image(path=DIAGRAM_FILE)),
        UserMessage(f"Where does {component} sit in this architecture, and what does it talk to?"),
    ]
