from mcp_types import Completion, CompletionArgument, CompletionContext, PromptReference, ResourceTemplateReference

from mcp.server import MCPServer

mcp = MCPServer("GitHub Explorer")

LANGUAGES = ["go", "javascript", "python", "rust", "typescript"]

REPOS_BY_OWNER = {
    "modelcontextprotocol": ["python-sdk", "typescript-sdk", "inspector"],
    "pydantic": ["pydantic", "pydantic-ai", "logfire"],
}


@mcp.resource("github://repos/{owner}/{repo}")
def github_repo(owner: str, repo: str) -> str:
    """A GitHub repository."""
    return f"Repository: {owner}/{repo}"


@mcp.prompt()
def review_code(language: str, code: str) -> str:
    """Review a snippet of code."""
    return f"Review this {language} code:\n{code}"


@mcp.completion()
async def handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    if isinstance(ref, PromptReference) and argument.name == "language":
        return Completion(values=[lang for lang in LANGUAGES if lang.startswith(argument.value)])
    if isinstance(ref, ResourceTemplateReference) and argument.name == "repo":
        if context is None or context.arguments is None:
            return None
        repos = REPOS_BY_OWNER.get(context.arguments.get("owner", ""), [])
        return Completion(values=[repo for repo in repos if repo.startswith(argument.value)])
    return None
