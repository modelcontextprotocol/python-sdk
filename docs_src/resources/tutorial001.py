from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.resource("config://app")
def get_config() -> str:
    """The active shop configuration."""
    return "theme=dark\nlanguage=en"
