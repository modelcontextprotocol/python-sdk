"""Read the negotiated protocol version inside a tool handler (initialize handshake)."""

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("custom-version-example")

    @mcp.tool()
    def protocol_info(ctx: Context) -> str:
        """Return the protocol version this connection negotiated."""
        return ctx.request_context.protocol_version

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
