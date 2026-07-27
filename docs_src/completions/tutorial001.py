from mcp.server import MCPServer

mcp = MCPServer("GitHub Explorer")


@mcp.resource("github://repos/{owner}/{repo}")
def github_repo(owner: str, repo: str) -> str:
    """A GitHub repository."""
    return f"Repository: {owner}/{repo}"


@mcp.prompt()
def review_code(language: str, code: str) -> str:
    """Review a snippet of code."""
    return f"Review this {language} code:\n{code}"
