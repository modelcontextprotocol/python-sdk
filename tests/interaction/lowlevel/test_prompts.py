"""Prompt interactions against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    INVALID_PARAMS,
    ErrorData,
    GetPromptResult,
    ListPromptsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("prompts:list:basic")
async def test_list_prompts_returns_registered_prompts() -> None:
    """The prompts returned by the handler reach the client with their argument declarations intact."""

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        return ListPromptsResult(
            prompts=[
                Prompt(
                    name="code_review",
                    description="Review a piece of code.",
                    arguments=[
                        PromptArgument(name="code", description="The code to review.", required=True),
                        PromptArgument(name="style_guide", description="Optional style guide to apply."),
                    ],
                ),
                Prompt(name="daily_standup"),
            ]
        )

    server = Server("prompter", on_list_prompts=list_prompts)

    async with Client(server) as client:
        result = await client.list_prompts()

    assert result == snapshot(
        ListPromptsResult(
            prompts=[
                Prompt(
                    name="code_review",
                    description="Review a piece of code.",
                    arguments=[
                        PromptArgument(name="code", description="The code to review.", required=True),
                        PromptArgument(name="style_guide", description="Optional style guide to apply."),
                    ],
                ),
                Prompt(name="daily_standup"),
            ]
        )
    )


@requirement("prompts:get:arguments")
async def test_get_prompt_substitutes_arguments() -> None:
    """Arguments supplied by the client reach the prompt handler; the templated message comes back."""

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "greet"
        assert params.arguments is not None
        return GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(text=f"Hello, {params.arguments['name']}!"))],
        )

    server = Server("prompter", on_get_prompt=get_prompt)

    async with Client(server) as client:
        result = await client.get_prompt("greet", {"name": "Ada"})

    assert result == snapshot(
        GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(text="Hello, Ada!"))],
        )
    )


@requirement("prompts:get:multi-message")
async def test_get_prompt_multiple_messages_preserve_roles_and_order() -> None:
    """A prompt returning a user/assistant conversation reaches the client with roles and order intact."""

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "geography_quiz"
        return GetPromptResult(
            messages=[
                PromptMessage(role="user", content=TextContent(text="What is the capital of France?")),
                PromptMessage(role="assistant", content=TextContent(text="The capital of France is Paris.")),
                PromptMessage(role="user", content=TextContent(text="And of Italy?")),
            ]
        )

    server = Server("prompter", on_get_prompt=get_prompt)

    async with Client(server) as client:
        result = await client.get_prompt("geography_quiz")

    assert result == snapshot(
        GetPromptResult(
            messages=[
                PromptMessage(role="user", content=TextContent(text="What is the capital of France?")),
                PromptMessage(role="assistant", content=TextContent(text="The capital of France is Paris.")),
                PromptMessage(role="user", content=TextContent(text="And of Italy?")),
            ]
        )
    )


@requirement("prompts:get:unknown-name")
async def test_get_prompt_unknown_name_is_protocol_error() -> None:
    """A handler that rejects an unrecognised prompt name with MCPError produces a JSON-RPC error.

    The error's code and message chosen by the handler reach the client verbatim.
    """

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown prompt: {params.name}")

    server = Server("prompter", on_get_prompt=get_prompt)

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("nope")

    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_PARAMS, message="Unknown prompt: nope"))
