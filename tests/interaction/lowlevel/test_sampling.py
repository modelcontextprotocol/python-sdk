"""Sampling interactions against the low-level Server, driven through the public Client API.

Each test nests a sampling/createMessage request inside a tool call: the tool handler calls
ctx.session.create_message(), the client's sampling callback answers it, and the handler
round-trips what it received back to the test through its tool result.
"""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    ErrorData,
    ImageContent,
    ModelHint,
    ModelPreferences,
    SamplingMessage,
    TextContent,
    ToolResultContent,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("sampling:create:basic")
@requirement("tools:call:sampling-roundtrip")
async def test_create_message_round_trip() -> None:
    """A handler's sampling request is answered by the client callback, and the callback's result
    (role, content, model, stop reason) is returned to the handler.
    """
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))],
            max_tokens=100,
        )
        assert isinstance(result.content, TextContent)
        return CallToolResult(content=[TextContent(text=f"{result.model}/{result.stop_reason}: {result.content.text}")])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        received.append(params)
        return CreateMessageResult(
            role="assistant",
            content=TextContent(text="Hello to you too."),
            model="mock-llm-1",
            stop_reason="endTurn",
        )

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="mock-llm-1/endTurn: Hello to you too.")]))
    assert received == snapshot(
        [
            CreateMessageRequestParams(
                _meta={},
                messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))],
                max_tokens=100,
            )
        ]
    )


@requirement("sampling:create:include-context")
@requirement("sampling:create:model-preferences")
@requirement("sampling:create:system-prompt")
async def test_create_message_params_reach_callback() -> None:
    """Every sampling parameter the handler supplies arrives at the client callback unchanged."""
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(text="Pick a model."))],
            max_tokens=50,
            system_prompt="You are terse.",
            include_context="thisServer",
            temperature=0.7,
            stop_sequences=["\n\n", "END"],
            model_preferences=ModelPreferences(
                hints=[ModelHint(name="claude"), ModelHint(name="gpt")],
                cost_priority=0.2,
                speed_priority=0.3,
                intelligence_priority=0.9,
            ),
        )
        assert isinstance(result.content, TextContent)
        return CallToolResult(content=[TextContent(text=result.content.text)])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        received.append(params)
        return CreateMessageResult(role="assistant", content=TextContent(text="ok"), model="mock-llm-1")

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")]))
    assert received == snapshot(
        [
            CreateMessageRequestParams(
                _meta={},
                messages=[SamplingMessage(role="user", content=TextContent(text="Pick a model."))],
                model_preferences=ModelPreferences(
                    hints=[ModelHint(name="claude"), ModelHint(name="gpt")],
                    cost_priority=0.2,
                    speed_priority=0.3,
                    intelligence_priority=0.9,
                ),
                system_prompt="You are terse.",
                include_context="thisServer",
                temperature=0.7,
                max_tokens=50,
                stop_sequences=["\n\n", "END"],
            )
        ]
    )


@requirement("sampling:create-message:image-content")
async def test_create_message_request_with_image_content_reaches_callback() -> None:
    """A sampling request message carrying image content arrives at the client callback intact.

    This is the server-to-client direction: the server includes an image in the conversation it
    asks the client to sample from.
    """
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="describe_image", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "describe_image"
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=ImageContent(data="aW1n", mime_type="image/png"))],
            max_tokens=100,
        )
        assert isinstance(result.content, TextContent)
        return CallToolResult(content=[TextContent(text=result.content.text)])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        received.append(params)
        image = params.messages[0].content
        assert isinstance(image, ImageContent)
        return CreateMessageResult(
            role="assistant",
            content=TextContent(text=f"described {image.mime_type} ({image.data})"),
            model="mock-vision-1",
        )

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("describe_image", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="described image/png (aW1n)")]))
    assert received == snapshot(
        [
            CreateMessageRequestParams(
                _meta={},
                messages=[SamplingMessage(role="user", content=ImageContent(data="aW1n", mime_type="image/png"))],
                max_tokens=100,
            )
        ]
    )


@requirement("sampling:create-message:image-content")
async def test_create_message_result_with_image_content_returns_to_handler() -> None:
    """A sampling result whose content is an image is returned to the requesting handler intact.

    This is the client-to-server direction: the model's response is an image rather than text.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="draw", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "draw"
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(text="Draw a cat."))],
            max_tokens=100,
        )
        image = result.content
        assert isinstance(image, ImageContent)
        return CallToolResult(content=[TextContent(text=f"{result.model}: {image.mime_type} {image.data}")])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        return CreateMessageResult(
            role="assistant",
            content=ImageContent(data="Y2F0", mime_type="image/png"),
            model="mock-vision-1",
        )

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("draw", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="mock-vision-1: image/png Y2F0")]))


@requirement("sampling:error:user-rejected")
async def test_create_message_callback_error() -> None:
    """A sampling callback that answers with an error surfaces to the requesting handler as an MCPError.

    The error here is the spec's own example for a user rejecting a sampling request (code -1);
    the callback's code and message reach the handler verbatim, whatever they are.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))],
                max_tokens=100,
            )
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # the callback always answers with an error

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(context: ClientRequestContext, params: CreateMessageRequestParams) -> ErrorData:
        return ErrorData(code=-1, message="User rejected sampling request")

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-1: User rejected sampling request")]))


@requirement("sampling:create-message:not-supported")
async def test_create_message_without_callback_is_error() -> None:
    """A sampling request to a client with no sampling callback fails with the SDK's default error."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))],
                max_tokens=100,
            )
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # create_message cannot succeed without a client callback

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-32600: Sampling not supported")]))


@requirement("sampling:tools:server-gated-by-capability")
async def test_create_message_with_tools_is_rejected_for_unsupporting_client() -> None:
    """A tool-enabled sampling request to a client that has not declared sampling.tools never leaves the server.

    The client supports plain sampling but cannot declare the tools sub-capability (Client does not
    expose it), so the server-side validator rejects the request before anything reaches the wire.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(text="What is the weather?"))],
                max_tokens=100,
                tools=[types.Tool(name="get_weather", input_schema={"type": "object"})],
            )
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # the validator rejects every tool-enabled request

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        """Declares the plain sampling capability; never invoked because the request is rejected first."""
        raise NotImplementedError

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="-32602: Client does not support sampling tools capability")])
    )


@requirement("sampling:tool-result:no-mixed-content")
async def test_create_message_with_unbalanced_tool_messages_is_rejected() -> None:
    """A sampling request whose messages mix tool results with other content never leaves the server.

    The message-structure validation runs inside create_message before the request is sent, even
    when no tools are passed, so the client callback is never invoked and the handler observes the
    ValueError directly.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="summarise_tools", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "summarise_tools"
        try:
            await ctx.session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=[
                            ToolResultContent(tool_use_id="call-1", content=[TextContent(text="42")]),
                            TextContent(text="Also, a comment alongside the result."),
                        ],
                    )
                ],
                max_tokens=100,
            )
        except ValueError as exc:
            return CallToolResult(content=[TextContent(text=f"{type(exc).__name__}: {exc}")])
        raise NotImplementedError  # the validator rejects the malformed messages before sending

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        """Declares the sampling capability; never invoked because the request is rejected first."""
        raise NotImplementedError

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("summarise_tools", {})

    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(text="ValueError: The last message must contain only tool_result content if any is present")
            ]
        )
    )
