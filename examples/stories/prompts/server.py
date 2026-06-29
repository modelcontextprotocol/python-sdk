"""Prompts primitive: register templates, list, render, complete an argument."""

from mcp_types import Completion, CompletionArgument, CompletionContext, PromptReference, ResourceTemplateReference

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts.base import AssistantMessage, Message, UserMessage
from stories._hosting import run_server_from_args

LANGUAGES = ["python", "pytorch", "rust", "go", "typescript"]


def build_server() -> MCPServer:
    mcp = MCPServer("prompts-example")

    @mcp.prompt(title="Greeting")
    def greet(name: str) -> str:
        """Ask the model to greet someone by name."""
        return f"Write a one-line greeting for {name}."

    @mcp.prompt(title="Code Review")
    def code_review(language: str, code: str) -> list[Message]:
        """Ask the model to review a code snippet."""
        return [
            UserMessage(f"Review this {language} code for bugs and idioms:\n\n{code}"),
            AssistantMessage("I'll review it. Let me read through the code first."),
        ]

    @mcp.completion()
    async def complete(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        if isinstance(ref, PromptReference) and ref.name == "code_review" and argument.name == "language":
            matches = [lang for lang in LANGUAGES if lang.startswith(argument.value)]
            return Completion(values=matches, total=len(matches), has_more=False)
        return None

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
