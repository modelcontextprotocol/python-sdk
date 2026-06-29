"""Prompt interactions against the low-level Server, driven through the public Client API."""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    AudioContent,
    EmbeddedResource,
    ErrorData,
    GetPromptResult,
    Icon,
    ImageContent,
    ListPromptsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    TextResourceContents,
)

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("prompts:list:basic")
async def test_list_prompts_returns_registered_prompts(connect: Connect) -> None:
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
                    icons=[Icon(src="https://example.com/review.png", mime_type="image/png", sizes=["48x48"])],
                ),
                Prompt(name="daily_standup"),
            ]
        )

    server = Server("prompter", on_list_prompts=list_prompts)

    async with connect(server) as client:
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
                    icons=[Icon(src="https://example.com/review.png", mime_type="image/png", sizes=["48x48"])],
                ),
                Prompt(name="daily_standup"),
            ]
        )
    )


@requirement("prompts:get:with-args")
async def test_get_prompt_substitutes_arguments(connect: Connect) -> None:
    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "greet"
        assert params.arguments is not None
        return GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(text=f"Hello, {params.arguments['name']}!"))],
        )

    server = Server("prompter", on_get_prompt=get_prompt)

    async with connect(server) as client:
        result = await client.get_prompt("greet", {"name": "Ada"})

    assert result == snapshot(
        GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(text="Hello, Ada!"))],
        )
    )


@requirement("prompts:get:multi-message")
async def test_get_prompt_multiple_messages_preserve_roles_and_order(connect: Connect) -> None:
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

    async with connect(server) as client:
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


@requirement("prompts:get:no-args")
async def test_get_prompt_without_arguments_returns_the_messages(connect: Connect) -> None:
    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "static"
        assert params.arguments is None
        return GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="Say hello."))])

    server = Server("prompter", on_get_prompt=get_prompt)

    async with connect(server) as client:
        result = await client.get_prompt("static")

    assert result == snapshot(
        GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="Say hello."))])
    )


@requirement("prompts:get:content:image")
@requirement("prompts:get:content:audio")
@requirement("prompts:get:content:embedded-resource")
async def test_get_prompt_with_non_text_content_round_trips(connect: Connect) -> None:
    """One snapshot proves all three tagged content types round-trip; base64 `aW1n`/`YXVk` decode to `img`/`aud`."""

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "media"
        return GetPromptResult(
            messages=[
                PromptMessage(role="user", content=ImageContent(data="aW1n", mime_type="image/png")),
                PromptMessage(role="assistant", content=AudioContent(data="YXVk", mime_type="audio/wav")),
                PromptMessage(
                    role="user",
                    content=EmbeddedResource(
                        resource=TextResourceContents(uri="resource://notes/1", mime_type="text/plain", text="attached")
                    ),
                ),
            ]
        )

    server = Server("prompter", on_get_prompt=get_prompt)

    async with connect(server) as client:
        result = await client.get_prompt("media", {})

    assert result == snapshot(
        GetPromptResult(
            messages=[
                PromptMessage(role="user", content=ImageContent(data="aW1n", mime_type="image/png")),
                PromptMessage(role="assistant", content=AudioContent(data="YXVk", mime_type="audio/wav")),
                PromptMessage(
                    role="user",
                    content=EmbeddedResource(
                        resource=TextResourceContents(uri="resource://notes/1", mime_type="text/plain", text="attached")
                    ),
                ),
            ]
        )
    )


@requirement("prompts:get:unknown-name")
async def test_get_prompt_unknown_name_is_protocol_error(connect: Connect) -> None:
    """The handler's MCPError code and message reach the client verbatim as a JSON-RPC error."""

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown prompt: {params.name}")

    server = Server("prompter", on_get_prompt=get_prompt)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("nope")

    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_PARAMS, message="Unknown prompt: nope"))
