import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

mcp = FastMCP("Embedded Resource Prompt Example")


@mcp.prompt()
def review_file(filename: str) -> list[base.Message]:
    """Review a file with its contents embedded."""
    file_content = open(filename).read()
    return [
        base.UserMessage(
            content=types.TextContent(type="text", text=f"Please review {filename}:"),
        ),
        base.UserMessage(
            content=types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=f"file://{filename}",
                    text=file_content,
                    mimeType="text/plain",
                ),
            ),
        ),
    ]
