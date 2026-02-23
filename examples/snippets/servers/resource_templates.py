from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Template Example")


@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """Read a specific user's profile. The user_id is extracted from the URI."""
    return f'{{"user_id": "{user_id}", "name": "User {user_id}"}}'
