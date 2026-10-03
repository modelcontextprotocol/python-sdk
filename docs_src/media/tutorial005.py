from mcp.server import MCPServer
from mcp.types import EmbeddedResource, TextResourceContents

mcp = MCPServer("Brand kit")


@mcp.resource("brand://guidelines", mime_type="text/markdown")
def guidelines() -> str:
    """How to use the brand assets."""
    return "# Brand guidelines\n\nUse the primary colour for calls to action.\n"


@mcp.tool()
def brand_guidelines() -> EmbeddedResource:
    """The brand guidelines as a Markdown document."""
    return EmbeddedResource(
        resource=TextResourceContents(uri="brand://guidelines", mime_type="text/markdown", text=guidelines())
    )
