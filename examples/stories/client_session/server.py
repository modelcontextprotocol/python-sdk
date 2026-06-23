"""Minimal server for the client-session story (the teaching point is client-side)."""

from mcp.server.mcpserver import MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("client-session-example")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
