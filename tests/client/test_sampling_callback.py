import pytest
from mcp_types import (
    INVALID_REQUEST,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    SamplingMessage,
    TextContent,
    ToolUseContent,
)

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError


@pytest.mark.anyio
async def test_sampling_callback():
    server = MCPServer("test")

    callback_return = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="This is a response from the sampling callback"),
        model="test-model",
        stop_reason="endTurn",
    )

    async def sampling_callback(
        context: ClientRequestContext,
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        return callback_return

    @server.tool("test_sampling")
    async def test_sampling_tool(message: str, ctx: Context) -> bool:
        value = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=message))],
            max_tokens=100,
        )
        assert value == callback_return
        return True

    async with Client(server, sampling_callback=sampling_callback, mode="legacy") as client:
        result = await client.call_tool("test_sampling", {"message": "Test message for sampling"})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Without a sampling callback the client responds with an MCPError the tool body
    # doesn't catch, so it surfaces as a top-level JSON-RPC error, not an isError result.
    async with Client(server, mode="legacy") as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("test_sampling", {"message": "Test message for sampling"})
    assert exc_info.value.error.code == INVALID_REQUEST


@pytest.mark.anyio
async def test_create_message_backwards_compat_single_content():
    server = MCPServer("test")

    callback_return = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="Hello from LLM"),
        model="test-model",
        stop_reason="endTurn",
    )

    async def sampling_callback(
        context: ClientRequestContext,
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        return callback_return

    @server.tool("test_backwards_compat")
    async def test_tool(message: str, ctx: Context) -> bool:
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=message))],
            max_tokens=100,
        )
        assert isinstance(result, CreateMessageResult)
        assert isinstance(result.content, TextContent)
        assert result.content.text == "Hello from LLM"
        # content_as_list exists only on CreateMessageResultWithTools
        assert not hasattr(result, "content_as_list") or not callable(getattr(result, "content_as_list", None))
        return True

    async with Client(server, sampling_callback=sampling_callback, mode="legacy") as client:
        result = await client.call_tool("test_backwards_compat", {"message": "Test"})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"


@pytest.mark.anyio
async def test_create_message_result_with_tools_type():
    # Tests the type directly, not the create_message overload (which requires client capability setup)
    result = CreateMessageResultWithTools(
        role="assistant",
        content=ToolUseContent(type="tool_use", id="call_123", name="get_weather", input={"city": "SF"}),
        model="test-model",
        stop_reason="toolUse",
    )

    content_list = result.content_as_list
    assert len(content_list) == 1
    assert content_list[0].type == "tool_use"

    result_array = CreateMessageResultWithTools(
        role="assistant",
        content=[
            TextContent(type="text", text="Let me check the weather"),
            ToolUseContent(type="tool_use", id="call_456", name="get_weather", input={"city": "NYC"}),
        ],
        model="test-model",
        stop_reason="toolUse",
    )
    content_list_array = result_array.content_as_list
    assert len(content_list_array) == 2
    assert content_list_array[0].type == "text"
    assert content_list_array[1].type == "tool_use"
