"""Resources primitive: a static URI and an RFC-6570 template via @mcp.resource()."""

from mcp.server.mcpserver import MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("resources-example")

    @mcp.resource("config://app", mime_type="application/json")
    def app_config() -> str:
        """Static application config."""
        return '{"feature": true}'

    @mcp.resource("greeting://{name}")
    def greeting(name: str) -> str:
        """A greeting for the named subject."""
        return f"Hello, {name}!"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
