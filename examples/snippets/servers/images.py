"""Example showing image handling with MCPServer."""

import io

from PIL import Image as PILImage

from mcp.server.mcpserver import Image, MCPServer

mcp = MCPServer("Image Example")


@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a thumbnail from an image"""
    img = PILImage.open(image_path)
    img.thumbnail((100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")
