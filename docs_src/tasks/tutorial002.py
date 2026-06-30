from mcp_types import CallToolRequestParams

from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import Tasks

SLOW_TOOLS = {"transcode"}


def augment(params: CallToolRequestParams) -> bool:
    return params.name in SLOW_TOOLS


mcp = MCPServer("studio", extensions=[Tasks(augment=augment, default_ttl_ms=60_000)])


@mcp.tool()
def transcode(clip: str) -> str:
    """Transcode a clip to the house format."""
    return f"{clip} transcoded."


@mcp.tool()
def ping() -> str:
    """Liveness probe."""
    return "pong"
