"""Sampling interactions against the low-level Server, driven through the public Client API.

Each test nests a sampling/createMessage request inside a tool call: the tool handler calls
ctx.session.create_message(), the client's sampling callback answers it, and the handler
round-trips what it received back to the test through its tool result.
"""

import mcp_types as types
import pydantic
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    AudioContent,
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ErrorData,
    ImageContent,
    ModelHint,
    ModelPreferences,
    SamplingCapability,
    SamplingMessage,
    TextContent,
    ToolResultContent,
    ToolUseContent,
)

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("sampling:create:basic")
@requirement("tools:call:sampling-roundtrip")
async def test_create_message_round_trip(connect: Connect) -> None:
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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

    async with connect(server, sampling_callback=sampling_callback) as client:
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
@requirement("sampling:context:server-gated-by-capability")
async def test_create_message_params_reach_callback(connect: Connect) -> None:
    """Every sampling parameter the handler supplies arrives at the client callback unchanged.

    include_context="thisServer" arrives even though Client cannot declare sampling.context: the
    spec's SHOULD NOT is unenforced. See the divergence note on `sampling:context:server-gated-by-capability`.
    """
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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

    async with connect(server, sampling_callback=sampling_callback) as client:
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
async def test_create_message_request_with_image_content_reaches_callback(connect: Connect) -> None:
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="describe_image", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "describe_image"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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

    async with connect(server, sampling_callback=sampling_callback) as client:
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
async def test_create_message_result_with_image_content_returns_to_handler(connect: Connect) -> None:
    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="draw", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "draw"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("draw", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="mock-vision-1: image/png Y2F0")]))


@requirement("sampling:error:user-rejected")
async def test_create_message_callback_error(connect: Connect) -> None:
    """A callback ErrorData answer surfaces to the requesting handler as an MCPError, code and message verbatim."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
                messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))],
                max_tokens=100,
            )
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # the callback always answers with an error

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(context: ClientRequestContext, params: CreateMessageRequestParams) -> ErrorData:
        return ErrorData(code=-1, message="User rejected sampling request")

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-1: User rejected sampling request")]))


@requirement("sampling:create-message:not-supported")
async def test_create_message_without_callback_is_error(connect: Connect) -> None:
    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
                messages=[SamplingMessage(role="user", content=TextContent(text="Say hello."))],
                max_tokens=100,
            )
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # create_message cannot succeed without a client callback

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-32600: Sampling not supported")]))


@requirement("sampling:tools:server-gated-by-capability")
async def test_create_message_with_tools_is_rejected_for_unsupporting_client(connect: Connect) -> None:
    """Client cannot declare sampling.tools, so the validator rejects before anything reaches the wire."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="-32602: Client does not support sampling tools capability")])
    )


@requirement("sampling:tool-result:no-mixed-content")
async def test_create_message_with_mixed_tool_result_content_is_rejected(connect: Connect) -> None:
    """Rejected inside create_message before sending — validation runs even when no tools are passed."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="summarise_tools", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "summarise_tools"
        try:
            await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("summarise_tools", {})

    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(text="ValueError: The last message must contain only tool_result content if any is present")
            ]
        )
    )


@requirement("sampling:capability:declare")
async def test_a_client_with_a_sampling_callback_declares_the_sampling_capability(connect: Connect) -> None:
    """The snapshot pins an empty SamplingCapability: Client exposes no sampling_capabilities parameter."""
    captured: list[SamplingCapability | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="capabilities", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "capabilities"
        assert ctx.session.client_params is not None
        captured.append(ctx.session.client_params.capabilities.sampling)
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("introspector", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        """Registered only so the sampling capability is advertised; never called."""
        raise NotImplementedError

    async with connect(server, sampling_callback=sampling_callback) as client:
        await client.call_tool("capabilities", {})

    assert captured == snapshot([SamplingCapability()])


@requirement("sampling:create-message:audio-content")
async def test_create_message_request_with_audio_content_reaches_callback(connect: Connect) -> None:
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="transcribe", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "transcribe"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[SamplingMessage(role="user", content=AudioContent(data="c25k", mime_type="audio/wav"))],
            max_tokens=100,
        )
        assert isinstance(result.content, TextContent)
        return CallToolResult(content=[TextContent(text=result.content.text)])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        received.append(params)
        audio = params.messages[0].content
        assert isinstance(audio, AudioContent)
        return CreateMessageResult(
            role="assistant",
            content=TextContent(text=f"transcribed {audio.mime_type} ({audio.data})"),
            model="mock-audio-1",
        )

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("transcribe", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="transcribed audio/wav (c25k)")]))
    assert received == snapshot(
        [
            CreateMessageRequestParams(
                _meta={},
                messages=[SamplingMessage(role="user", content=AudioContent(data="c25k", mime_type="audio/wav"))],
                max_tokens=100,
            )
        ]
    )


@requirement("sampling:create-message:audio-content")
async def test_create_message_result_with_audio_content_returns_to_handler(connect: Connect) -> None:
    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="speak", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "speak"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[SamplingMessage(role="user", content=TextContent(text="Say hello, aloud."))],
            max_tokens=100,
        )
        audio = result.content
        assert isinstance(audio, AudioContent)
        return CallToolResult(content=[TextContent(text=f"{result.model}: {audio.mime_type} {audio.data}")])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        return CreateMessageResult(
            role="assistant",
            content=AudioContent(data="aGVsbG8=", mime_type="audio/wav"),
            model="mock-audio-1",
        )

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("speak", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="mock-audio-1: audio/wav aGVsbG8=")]))


@requirement("sampling:message:content-cardinality")
async def test_create_message_with_list_valued_message_content_reaches_callback(connect: Connect) -> None:
    received: list[CreateMessageRequestParams] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="caption", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "caption"
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[
                SamplingMessage(
                    role="user",
                    content=[
                        TextContent(text="Caption this image."),
                        ImageContent(data="aW1n", mime_type="image/png"),
                    ],
                )
            ],
            max_tokens=100,
        )
        assert isinstance(result.content, TextContent)
        return CallToolResult(content=[TextContent(text=result.content.text)])

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        received.append(params)
        content = params.messages[0].content
        assert isinstance(content, list)
        return CreateMessageResult(
            role="assistant", content=TextContent(text=f"{len(content)} blocks"), model="mock-llm-1"
        )

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("caption", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="2 blocks")]))
    assert received == snapshot(
        [
            CreateMessageRequestParams(
                _meta={},
                messages=[
                    SamplingMessage(
                        role="user",
                        content=[
                            TextContent(text="Caption this image."),
                            ImageContent(data="aW1n", mime_type="image/png"),
                        ],
                    )
                ],
                max_tokens=100,
            )
        ]
    )


@requirement("sampling:tool-use:server-preflight")
async def test_create_message_with_mismatched_tool_use_and_result_ids_is_rejected(connect: Connect) -> None:
    """The mismatch is rejected inside create_message, before the request is sent.

    The spec's client-side -32602 check is tracked separately at sampling:tool-use:result-balance.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="continue_tools", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "continue_tools"
        try:
            await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
                messages=[
                    SamplingMessage(
                        role="assistant",
                        content=[ToolUseContent(id="call-1", name="weather", input={})],
                    ),
                    SamplingMessage(
                        role="user",
                        content=[ToolResultContent(tool_use_id="call-WRONG", content=[TextContent(text="42")])],
                    ),
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

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("continue_tools", {})

    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(
                    text="ValueError: ids of tool_result blocks and tool_use blocks from previous message do not match"
                )
            ]
        )
    )


@requirement("sampling:result:no-tools-single-content")
async def test_array_content_result_for_a_tool_free_request_surfaces_as_a_validation_error(connect: Connect) -> None:
    """Divergence (see the requirement): the client should reject this result; instead server-side parsing raises.

    Only the exception type is asserted: the message is pydantic's and changes across releases.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask_model", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask_model"
        try:
            await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
                messages=[SamplingMessage(role="user", content=TextContent(text="Two thoughts, please."))],
                max_tokens=100,
            )
        except pydantic.ValidationError as exc:
            return CallToolResult(content=[TextContent(text=type(exc).__name__)])
        raise NotImplementedError  # the array-content result fails server-side parsing every time

    server = Server("sampler", on_list_tools=list_tools, on_call_tool=call_tool)

    async def sampling_callback(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResultWithTools:
        return CreateMessageResultWithTools(
            role="assistant",
            content=[TextContent(text="First thought."), TextContent(text="Second thought.")],
            model="mock-llm-1",
        )

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("ask_model", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ValidationError")]))
