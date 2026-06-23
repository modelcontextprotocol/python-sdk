"""One MCPServer factory that serves both the 2025 handshake era and the 2026 stateless era."""

from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.version import MODERN_PROTOCOL_VERSIONS
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("dual-era-example", instructions="A small dual-era demo server.")

    @mcp.tool()
    async def greet(name: str, ctx: Context) -> str:
        """Greet the caller and report which protocol era served the request."""
        pv = ctx.request_context.protocol_version
        era = "modern" if pv in MODERN_PROTOCOL_VERSIONS else "legacy"
        return f"Hello, {name}! (served on the {era} era at {pv})"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
