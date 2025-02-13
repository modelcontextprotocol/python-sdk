import pytest

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
        message: CreateMessageRequestParams,
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

    async with create_session(
        server._mcp_server, sampling_callback=sampling_callback
    ) as client_session:
        # Make a request to trigger sampling callback
        assert await client_session.call_tool(
            "test_sampling", {"message": "Test message for sampling"}
        )
