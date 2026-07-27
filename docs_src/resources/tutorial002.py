from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.resource("config://app")
def get_config() -> str:
    """The active shop configuration."""
    return "theme=dark\nlanguage=en"


@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """A customer's profile."""
    return f"User {user_id}: 12 orders since 2021."
