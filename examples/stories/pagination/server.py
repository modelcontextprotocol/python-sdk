"""Six static resources on MCPServer; its built-in registry serves them as one page."""

from mcp.server.mcpserver import MCPServer
from stories._hosting import run_server_from_args

WORDS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")


def build_server() -> MCPServer:
    mcp = MCPServer("pagination-example")

    def register(word: str) -> None:
        @mcp.resource(f"word://{word}", name=word, mime_type="text/plain")
        def read() -> str:
            return word

    for word in WORDS:
        register(word)

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
