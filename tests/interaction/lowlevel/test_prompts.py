"""Prompt interactions against the low-level Server, driven through the public Client API."""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    AudioContent,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    EmbeddedResource,
    ErrorData,
    GetPromptResult,
    Icon,
    ImageContent,
    InputRequiredResult,
    InputResponses,
    ListPromptsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    ResourceLink,
    TextContent,
    TextResourceContents,
)

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("prompts:list:basic")
async def test_list_prompts_returns_registered_prompts(connect: Connect) -> None:
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
    """Arguments supplied by the client reach the prompt handler; the templated message comes back."""

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
    """A prompt fetched with no arguments delivers None as the handler's arguments and returns its messages."""

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
    """Prompt messages can carry image, audio, and embedded-resource content; all reach the client.

    A single full-result snapshot proves all three content types round-trip: each block in the result
    is one of the three behaviours under test. Tiny fixed base64 payloads ("aW1n" is b"img", "YXVk"
    is b"aud") so the snapshot pins the exact bytes.
    """

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


@requirement("prompts:get:content:resource-link")
async def test_get_prompt_resource_link_content_round_trips(connect: Connect) -> None:
    """A resource_link prompt message reaches the client with URI and descriptive fields intact. Spec-mandated."""

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "entry_point"
        return GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=ResourceLink(
                        uri="file:///project/src/main.rs",
                        name="main.rs",
                        description="Primary application entry point",
                        mime_type="text/x-rust",
                    ),
                )
            ]
        )

    server = Server("prompter", on_get_prompt=get_prompt)

    async with connect(server) as client:
        result = await client.get_prompt("entry_point")

    assert result == snapshot(
        GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=ResourceLink(
                        name="main.rs",
                        uri="file:///project/src/main.rs",
                        description="Primary application entry point",
                        mime_type="text/x-rust",
                    ),
                )
            ]
        )
    )


@requirement("prompts:get:unknown-name")
async def test_get_prompt_unknown_name_is_protocol_error(connect: Connect) -> None:
    """A handler that rejects an unrecognised prompt name with MCPError produces a JSON-RPC error.

    The error's code and message chosen by the handler reach the client verbatim.
    """

    async def get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> GetPromptResult:
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown prompt: {params.name}")

    server = Server("prompter", on_get_prompt=get_prompt)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("nope")

    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_PARAMS, message="Unknown prompt: nope"))


@requirement("prompts:mrtr:get:basic")
async def test_get_prompt_input_required_is_fulfilled_and_the_retry_returns_the_messages(connect: Connect) -> None:
    """A prompts/get answered with input_required is fulfilled by the elicitation callback and retried.

    Spec-mandated: prompts/get is an MRTR-supported request (basic/patterns/mrtr, Supported Requests).
    """
    sent = ElicitRequestFormParams(
        message="Who is reading?",
        requested_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    )
    answer = ElicitResult(action="accept", content={"name": "alice"})
    state = "state-1"
    rounds: list[tuple[InputResponses | None, str | None]] = []
    callback_received: list[ElicitRequestFormParams] = []

    async def get_prompt(
        ctx: ServerRequestContext, params: types.GetPromptRequestParams
    ) -> GetPromptResult | InputRequiredResult:
        assert params.name == "greet"
        rounds.append((params.input_responses, params.request_state))
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"who": ElicitRequest(params=sent)}, request_state=state)
        response = params.input_responses["who"]
        assert isinstance(response, ElicitResult)
        assert response.content is not None
        return GetPromptResult(
            messages=[PromptMessage(role="user", content=TextContent(text=f"Hello, {response.content['name']}!"))]
        )

    server = Server("prompter", on_get_prompt=get_prompt)

    async def elicit(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        callback_received.append(params)
        return answer

    async with connect(server, elicitation_callback=elicit) as client:
        result = await client.get_prompt("greet")

    assert result == snapshot(
        GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="Hello, alice!"))])
    )
    assert callback_received == [sent]
    assert rounds == [(None, None), ({"who": answer}, state)]
