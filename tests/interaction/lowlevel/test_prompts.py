"""Prompt interactions against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import McpError
from mcp.server.lowlevel import Server
from mcp.types import (
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
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("prompts:list:basic")
async def test_list_prompts_returns_registered_prompts(connect: Connect) -> None:
    """The prompts returned by the handler reach the client with their argument declarations intact."""
    server = Server("prompter")

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="code_review",
                description="Review a piece of code.",
                arguments=[
                    PromptArgument(name="code", description="The code to review.", required=True),
                    PromptArgument(name="style_guide", description="Optional style guide to apply."),
                ],
                icons=[Icon(src="https://example.com/review.png", mimeType="image/png", sizes=["48x48"])],
            ),
            Prompt(name="daily_standup"),
        ]

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
                    icons=[Icon(src="https://example.com/review.png", mimeType="image/png", sizes=["48x48"])],
                ),
                Prompt(name="daily_standup"),
            ]
        )
    )


@requirement("prompts:get:with-args")
async def test_get_prompt_substitutes_arguments(connect: Connect) -> None:
    """Arguments supplied by the client reach the prompt handler; the templated message comes back."""
    server = Server("prompter")

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        assert name == "greet"
        assert arguments is not None
        return GetPromptResult(
            description="A personalised greeting.",
            messages=[
                PromptMessage(role="user", content=TextContent(type="text", text=f"Hello, {arguments['name']}!"))
            ],
        )

    async with connect(server) as client:
        result = await client.get_prompt("greet", {"name": "Ada"})

    assert result == snapshot(
        GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text="Hello, Ada!"))],
        )
    )


@requirement("prompts:get:multi-message")
async def test_get_prompt_multiple_messages_preserve_roles_and_order(connect: Connect) -> None:
    """A prompt returning a user/assistant conversation reaches the client with roles and order intact."""
    server = Server("prompter")

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        assert name == "geography_quiz"
        return GetPromptResult(
            messages=[
                PromptMessage(role="user", content=TextContent(type="text", text="What is the capital of France?")),
                PromptMessage(
                    role="assistant", content=TextContent(type="text", text="The capital of France is Paris.")
                ),
                PromptMessage(role="user", content=TextContent(type="text", text="And of Italy?")),
            ]
        )

    async with connect(server) as client:
        result = await client.get_prompt("geography_quiz")

    assert result == snapshot(
        GetPromptResult(
            messages=[
                PromptMessage(role="user", content=TextContent(type="text", text="What is the capital of France?")),
                PromptMessage(
                    role="assistant", content=TextContent(type="text", text="The capital of France is Paris.")
                ),
                PromptMessage(role="user", content=TextContent(type="text", text="And of Italy?")),
            ]
        )
    )


@requirement("prompts:get:no-args")
async def test_get_prompt_without_arguments_returns_the_messages(connect: Connect) -> None:
    """A prompt fetched with no arguments delivers None as the handler's arguments and returns its messages."""
    server = Server("prompter")

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        assert name == "static"
        assert arguments is None
        return GetPromptResult(
            messages=[PromptMessage(role="user", content=TextContent(type="text", text="Say hello."))]
        )

    async with connect(server) as client:
        result = await client.get_prompt("static")

    assert result == snapshot(
        GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(type="text", text="Say hello."))])
    )


@requirement("prompts:get:content:image")
@requirement("prompts:get:content:audio")
@requirement("prompts:get:content:embedded-resource")
async def test_get_prompt_with_non_text_content_round_trips(connect: Connect) -> None:
    """Prompt messages can carry image, audio, and embedded-resource content; all reach the client.

    A single full-result snapshot proves all three content types round-trip: each block in the result
    is one of the three behaviours under test. Tiny fixed base64 payloads ("aW1n" is b"img", "YXVk"
    is b"aud") so the snapshot pins the exact bytes.
    """
    server = Server("prompter")

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        assert name == "media"
        return GetPromptResult(
            messages=[
                PromptMessage(role="user", content=ImageContent(type="image", data="aW1n", mimeType="image/png")),
                PromptMessage(role="assistant", content=AudioContent(type="audio", data="YXVk", mimeType="audio/wav")),
                PromptMessage(
                    role="user",
                    content=EmbeddedResource(
                        type="resource",
                        resource=TextResourceContents(uri="resource://notes/1", mimeType="text/plain", text="attached"),
                    ),
                ),
            ]
        )

    async with connect(server) as client:
        result = await client.get_prompt("media", {})

    assert result == snapshot(
        GetPromptResult(
            messages=[
                PromptMessage(role="user", content=ImageContent(type="image", data="aW1n", mimeType="image/png")),
                PromptMessage(role="assistant", content=AudioContent(type="audio", data="YXVk", mimeType="audio/wav")),
                PromptMessage(
                    role="user",
                    content=EmbeddedResource(
                        type="resource",
                        resource=TextResourceContents(uri="resource://notes/1", mimeType="text/plain", text="attached"),
                    ),
                ),
            ]
        )
    )


@requirement("prompts:get:unknown-name")
async def test_get_prompt_unknown_name_is_protocol_error(connect: Connect) -> None:
    """A handler that rejects an unrecognised prompt name with McpError produces a JSON-RPC error.

    The error's code and message chosen by the handler reach the client verbatim.
    """
    server = Server("prompter")

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown prompt: {name}"))

    async with connect(server) as client:
        with pytest.raises(McpError) as exc_info:
            await client.get_prompt("nope")

    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_PARAMS, message="Unknown prompt: nope"))
