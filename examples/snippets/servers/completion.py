from mcp.server.fastmcp import FastMCP
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

mcp = FastMCP(name="Example")


@mcp.resource("github://repos/{owner}/{repo}")
def github_repo(owner: str, repo: str) -> str:
    """GitHub repository resource."""
    return f"Repository: {owner}/{repo}"


@mcp.prompt(description="Code review prompt")
def review_code(language: str, code: str) -> str:
    """Generate a code review."""
    return f"Review this {language} code:\n{code}"


@mcp.completion()
async def handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    """Provide completions for prompts and resources."""

    # Complete programming languages for the prompt
    if isinstance(ref, PromptReference):
        if ref.name == "review_code" and argument.name == "language":
            languages = ["python", "javascript", "typescript", "go", "rust"]
            return Completion(
                values=[lang for lang in languages if lang.startswith(argument.value)],
                hasMore=False,
            )

    # Complete repository names for GitHub resources
    if isinstance(ref, ResourceTemplateReference):
        if ref.uri == "github://repos/{owner}/{repo}" and argument.name == "repo":
            if context and context.arguments and context.arguments.get("owner") == "modelcontextprotocol":
                repos = ["python-sdk", "typescript-sdk", "specification"]
                return Completion(values=repos, hasMore=False)

    return None
