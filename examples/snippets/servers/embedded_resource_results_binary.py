import base64

from mcp.server.fastmcp import FastMCP
from mcp.types import BlobResourceContents, EmbeddedResource

mcp = FastMCP("Binary Embedded Resource Example")


@mcp.tool()
def read_binary_file(path: str) -> EmbeddedResource:
    """Read a binary file and return it as an embedded resource."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(
            uri=f"file://{path}",
            blob=data,
            mimeType="application/octet-stream",
        ),
    )
