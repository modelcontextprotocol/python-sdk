"""A small modern server whose DiscoverResult a client persists for zero-RTT reconnect."""

from mcp.server.mcpserver import MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer(
        "reconnect-example",
        version="1.0.0",
        instructions="Call add(a, b) to sum two integers.",
    )

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
