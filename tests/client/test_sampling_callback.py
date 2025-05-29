import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    SamplingMessage,
    TextContent,
)


@pytest.mark.anyio
async def test_sampling_callback():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    callback_return = CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text", text="This is a response from the sampling callback"
        ),
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
            messages=[
                SamplingMessage(
                    role="user", content=TextContent(type="text", text=message)
                )
            ],
            max_tokens=100,
        )
        assert value == callback_return
        return True

    # Test with sampling callback
    async with create_session(
        server._mcp_server, sampling_callback=sampling_callback
    ) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool(
            "test_sampling", {"message": "Test message for sampling"}
        )
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Test without sampling callback
    async with create_session(server._mcp_server) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool(
            "test_sampling", {"message": "Test message for sampling"}
        )
        assert result.isError is True
        assert isinstance(result.content[0], TextContent)
        assert (
            result.content[0].text
            == "Error executing tool test_sampling: Sampling not supported"
        )


@pytest.mark.anyio
async def test_concurrent_sampling_callback():
    """Test multiple concurrent sampling calls using time-sort verification."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    # Track completion order using time-sort approach
    completion_order = []

    async def sampling_callback(
        context: RequestContext[ClientSession, None],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        # Extract delay from the message content (e.g., "delay_0.3")
        message_text = params.messages[0].content.text
        if message_text.startswith("delay_"):
            delay = float(message_text.split("_")[1])
            # Simulate different LLM response times
            await anyio.sleep(delay)
            completion_order.append(delay)
            return CreateMessageResult(
                role="assistant",
                content=TextContent(type="text", text=f"Response after {delay}s"),
                model="test-model",
                stopReason="endTurn",
            )

        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Default response"),
            model="test-model",
            stopReason="endTurn",
        )

    @server.tool("concurrent_sampling_tool")
    async def concurrent_sampling_tool():
        """Tool that makes multiple concurrent sampling calls."""
        # Use TaskGroup to make multiple concurrent sampling calls
        # Using out-of-order durations: 0.6s, 0.2s, 0.4s
        # If concurrent, should complete in order: 0.2s, 0.4s, 0.6s
        async with anyio.create_task_group() as tg:
            results = {}

            async def make_sampling_call(call_id: str, delay: float):
                result = await server.get_context().session.create_message(
                    messages=[
                        SamplingMessage(
                            role="user",
                            content=TextContent(type="text", text=f"delay_{delay}"),
                        )
                    ],
                    max_tokens=100,
                )
                results[call_id] = result

            # Start operations with out-of-order timing
            tg.start_soon(make_sampling_call, "slow_call", 0.6)  # Should finish last
            tg.start_soon(make_sampling_call, "fast_call", 0.2)  # Should finish first
            tg.start_soon(
                make_sampling_call, "medium_call", 0.4
            )  # Should finish middle

        # Combine results to show all completed
        combined_response = " | ".join(
            [
                results["slow_call"].content.text,
                results["fast_call"].content.text,
                results["medium_call"].content.text,
            ]
        )

        return combined_response

    # Test concurrent sampling calls with time-sort verification
    async with create_session(
        server._mcp_server, sampling_callback=sampling_callback
    ) as client_session:
        # Make a request that triggers multiple concurrent sampling calls
        result = await client_session.call_tool("concurrent_sampling_tool", {})

        assert result.isError is False
        assert isinstance(result.content[0], TextContent)

        # Verify all sampling calls completed with expected responses
        expected_result = (
            "Response after 0.6s | Response after 0.2s | Response after 0.4s"
        )
        assert result.content[0].text == expected_result

        # Key test: verify concurrent execution using time-sort
        # Started in order: 0.6s, 0.2s, 0.4s
        # Should complete in order: 0.2s, 0.4s, 0.6s (fastest first)
        assert len(completion_order) == 3
        assert completion_order == [
            0.2,
            0.4,
            0.6,
        ], f"Expected [0.2, 0.4, 0.6] but got {completion_order}"
