"""Example showing image handling with MCPServer."""

from PIL import Image as PILImage

from mcp.server.mcpserver import Image, MCPServer

mcp = MCPServer("Image Example")


@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a thumbnail from an image"""
    img = PILImage.open(image_path)
    img.thumbnail((100, 100))
    return Image(data=img.tobytes(), format="png")
