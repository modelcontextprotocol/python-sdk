import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.server.fastmcp.utilities.types import Image

mcp = FastMCP("Image Prompt Example")


@mcp.prompt()
def describe_image(image_path: str) -> list[base.Message]:
    """Prompt that includes an image for analysis."""
    img = Image(path=image_path)
    return [
        base.UserMessage(
            content=types.TextContent(type="text", text="Describe this image:"),
        ),
        base.UserMessage(
            content=img.to_image_content(),
        ),
    ]
