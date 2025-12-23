from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP(name="Context Resource Example")


@mcp.resource("resource://only_context")
def resource_only_context(ctx: Context[ServerSession, None]) -> str:
    """Resource that only receives context."""
    assert ctx is not None
    return "Resource with only context injected"
