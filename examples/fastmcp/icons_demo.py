"""
FastMCP Icons Demo Server

Demonstrates using icons with tools, resources, prompts, and implementation.
"""

import base64
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Icon

# Load the icon file and convert to data URI
icon_path = Path(__file__).parent / "mcp.png"
icon_data = base64.standard_b64encode(icon_path.read_bytes()).decode()
icon_data_uri = f"data:image/png;base64,{icon_data}"

icon_data = Icon(src=icon_data_uri, mimeType="image/png", sizes=["64x64"])

# Create server with icons in implementation
mcp = FastMCP("Icons Demo Server", website_url="https://github.com/modelcontextprotocol/python-sdk", icons=[icon_data])


@mcp.tool(icons=[icon_data])
def demo_tool(message: str) -> str:
    """A demo tool with an icon."""
    return message


@mcp.resource("demo://readme", icons=[icon_data])
def readme_resource() -> str:
    """A demo resource with an icon"""
    return "This resource has an icon"


@mcp.prompt("prompt_with_icon", icons=[icon_data])
def prompt_with_icon(text: str) -> str:
    """A demo prompt with an icon"""
    return text


@mcp.tool(
    icons=[
        Icon(src=icon_data_uri, mimeType="image/png", sizes=["16x16"]),
        Icon(src=icon_data_uri, mimeType="image/png", sizes=["32x32"]),
        Icon(src=icon_data_uri, mimeType="image/png", sizes=["64x64"]),
    ]
)
def multi_icon_tool(action: str) -> str:
    """A tool demonstrating multiple icons."""
    return "multi_icon_tool"


if __name__ == "__main__":
    # Run the server
    mcp.run()
