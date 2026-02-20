from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, TextResourceContents

mcp = FastMCP("Embedded Resource Example")


@mcp.tool()
def read_config(path: str) -> EmbeddedResource:
    """Read a config file and return it as an embedded resource."""
    with open(path) as f:
        content = f.read()
    return EmbeddedResource(
        type="resource",
        resource=TextResourceContents(
            uri=f"file://{path}",
            text=content,
            mimeType="application/json",
        ),
    )
