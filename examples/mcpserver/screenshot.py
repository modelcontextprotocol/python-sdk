"""MCPServer Screenshot Example

Give Claude a tool to capture and view screenshots.
"""

import io

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.types import Image
from mcp.types import ToolAnnotations

# Create server
mcp = MCPServer("Screenshot Demo")


# Both hints differ from the spec defaults, so they tell a client something:
# the tool only reads the local display and never reaches an external system.
@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
def take_screenshot() -> Image:
    """Take a screenshot of the user's screen and return it as an image. Use
    this tool anytime the user wants you to look at something they're doing.
    """
    import pyautogui

    buffer = io.BytesIO()

    # if the file exceeds ~1MB, it will be rejected by Claude
    screenshot = pyautogui.screenshot()
    screenshot.convert("RGB").save(buffer, format="JPEG", quality=60, optimize=True)
    return Image(data=buffer.getvalue(), format="jpeg")
