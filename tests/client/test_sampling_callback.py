import pytest

from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    SamplingMessage,
    TextContent,
    ToolUseContent,
)


@pytest.mark.anyio
async def test_sampling_callback():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    callback_return = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="This is a response from the sampling callback"),
        model="test-model",
        stopReason="endTurn",
    )

    async def sampling_callback(
        context: RequestContext[ClientSession, None],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        return callback_return

    @server.tool("test_sampling")
    async def test_sampling_tool(message: str):
        value = await server.get_context().session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=message))],
            max_tokens=100,
        )
        assert value == callback_return
        return True

    # Test with sampling callback
    async with create_session(server._mcp_server, sampling_callback=sampling_callback) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool("test_sampling", {"message": "Test message for sampling"})
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Test without sampling callback
    async with create_session(server._mcp_server) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool("test_sampling", {"message": "Test message for sampling"})
        assert result.isError is True
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Error executing tool test_sampling: Sampling not supported"


@pytest.mark.anyio
async def test_create_message_backwards_compat_single_content():
    """Test backwards compatibility: create_message without tools returns single content."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    # Callback returns single content (text)
    callback_return = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="Hello from LLM"),
        model="test-model",
        stopReason="endTurn",
    )

    async def sampling_callback(
        context: RequestContext[ClientSession, None],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        return callback_return

    @server.tool("test_backwards_compat")
    async def test_tool(message: str):
        # Call create_message WITHOUT tools
        result = await server.get_context().session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=message))],
            max_tokens=100,
        )
        # Backwards compat: result should be CreateMessageResult
        assert isinstance(result, CreateMessageResult)
        # Content should be single (not a list) - this is the key backwards compat check
        assert isinstance(result.content, TextContent)
        assert result.content.text == "Hello from LLM"
        # CreateMessageResult should NOT have content_as_list (that's on WithTools)
        assert not hasattr(result, "content_as_list") or not callable(getattr(result, "content_as_list", None))
        return True

    async with create_session(server._mcp_server, sampling_callback=sampling_callback) as client_session:
        result = await client_session.call_tool("test_backwards_compat", {"message": "Test"})
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"


@pytest.mark.anyio
async def test_create_message_result_with_tools_type():
    """Test that CreateMessageResultWithTools supports content_as_list."""
    # Test the type itself, not the overload (overload requires client capability setup)
    result = CreateMessageResultWithTools(
        role="assistant",
        content=ToolUseContent(type="tool_use", id="call_123", name="get_weather", input={"city": "SF"}),
        model="test-model",
        stopReason="toolUse",
    )

    # CreateMessageResultWithTools should have content_as_list
    content_list = result.content_as_list
    assert len(content_list) == 1
    assert content_list[0].type == "tool_use"

    # It should also work with array content
    result_array = CreateMessageResultWithTools(
        role="assistant",
        content=[
            TextContent(type="text", text="Let me check the weather"),
            ToolUseContent(type="tool_use", id="call_456", name="get_weather", input={"city": "NYC"}),
        ],
        model="test-model",
        stopReason="toolUse",
    )
    content_list_array = result_array.content_as_list
    assert len(content_list_array) == 2
    assert content_list_array[0].type == "text"
    assert content_list_array[1].type == "tool_use"
