"""Prompts primitive (lowlevel API): hand-built Prompt descriptors, GetPromptResult, completion."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

LANGUAGES = ["python", "pytorch", "rust", "go", "typescript"]

PROMPTS = [
    types.Prompt(
        name="greet",
        title="Greeting",
        description="Ask the model to greet someone by name.",
        arguments=[types.PromptArgument(name="name", required=True)],
    ),
    types.Prompt(
        name="code_review",
        title="Code Review",
        description="Ask the model to review a code snippet.",
        arguments=[
            types.PromptArgument(name="language", required=True),
            types.PromptArgument(name="code", required=True),
        ],
    ),
]


def build_server() -> Server[Any]:
    async def list_prompts(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=PROMPTS)

    async def get_prompt(ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams) -> types.GetPromptResult:
        args = params.arguments or {}
        if params.name == "greet":
            return types.GetPromptResult(
                description="Ask the model to greet someone by name.",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(text=f"Write a one-line greeting for {args['name']}."),
                    )
                ],
            )
        if params.name == "code_review":
            return types.GetPromptResult(
                description="Ask the model to review a code snippet.",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(
                            text=f"Review this {args['language']} code for bugs and idioms:\n\n{args['code']}"
                        ),
                    ),
                    types.PromptMessage(
                        role="assistant",
                        content=types.TextContent(text="I'll review it. Let me read through the code first."),
                    ),
                ],
            )
        raise NotImplementedError

    async def completion(ctx: ServerRequestContext[Any], params: types.CompleteRequestParams) -> types.CompleteResult:
        if (
            isinstance(params.ref, types.PromptReference)
            and params.ref.name == "code_review"
            and params.argument.name == "language"
        ):
            matches = [lang for lang in LANGUAGES if lang.startswith(params.argument.value)]
            return types.CompleteResult(completion=types.Completion(values=matches, total=len(matches), has_more=False))
        return types.CompleteResult(completion=types.Completion(values=[]))

    return Server(
        "prompts-example",
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
        on_completion=completion,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
