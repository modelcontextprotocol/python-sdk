from typing import Any

import pytest

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    SamplingMessage,
    TextContent,
)


@pytest.mark.anyio
async def test_server_create_message_progress_callback():
    """Test that ServerSession.create_message() accepts and passes through progress_callback."""
    server = MCPServer("test")

    # Track progress updates received by the server's progress callback
    progress_updates: list[dict[str, Any]] = []

    async def my_progress_callback(progress: float, total: float | None, message: str | None) -> None:
        progress_updates.append({"progress": progress, "total": total, "message": message})

    @server.tool("trigger_sampling")
    async def trigger_sampling_tool(text: str, ctx: Context) -> str:
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=text))],
            max_tokens=100,
            progress_callback=my_progress_callback,
        )
        assert isinstance(result.content, TextContent)
        return result.content.text

    async def sampling_callback(
        context: ClientRequestContext,
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        # Send progress notifications back to the server using the progress token
        if context.meta and "progress_token" in context.meta:  # pragma: no branch
            token = context.meta["progress_token"]
            await context.session.send_progress_notification(
                progress_token=token,
                progress=0.5,
                total=1.0,
                message="Halfway done",
            )
            await context.session.send_progress_notification(
                progress_token=token,
                progress=1.0,
                total=1.0,
                message="Complete",
            )

        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="LLM response"),
            model="test-model",
            stop_reason="endTurn",
        )

    async with Client(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("trigger_sampling", {"text": "Hello"})
        assert result.is_error is False

    # Verify the progress callback was invoked with correct values
    assert len(progress_updates) == 2
    assert progress_updates[0] == {"progress": 0.5, "total": 1.0, "message": "Halfway done"}
    assert progress_updates[1] == {"progress": 1.0, "total": 1.0, "message": "Complete"}


@pytest.mark.anyio
async def test_server_elicit_form_progress_callback():
    """Test that ServerSession.elicit_form() accepts and passes through progress_callback."""
    server = MCPServer("test")

    # Track progress updates received by the server's progress callback
    progress_updates: list[dict[str, Any]] = []

    async def my_progress_callback(progress: float, total: float | None, message: str | None) -> None:
        progress_updates.append({"progress": progress, "total": total, "message": message})

    @server.tool("trigger_elicitation")
    async def trigger_elicitation_tool(text: str, ctx: Context) -> str:
        result = await ctx.session.elicit_form(
            message=text,
            requested_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            progress_callback=my_progress_callback,
        )
        return result.action

    async def elicitation_callback(
        context: ClientRequestContext,
        params: ElicitRequestParams,
    ) -> ElicitResult:
        # Send progress notifications back to the server using the progress token
        if context.meta and "progress_token" in context.meta:  # pragma: no branch
            token = context.meta["progress_token"]
            await context.session.send_progress_notification(
                progress_token=token,
                progress=1.0,
                total=1.0,
                message="User responded",
            )

        return ElicitResult(
            action="accept",
            content={"name": "test"},
        )

    async with Client(server, elicitation_callback=elicitation_callback) as client:
        result = await client.call_tool("trigger_elicitation", {"text": "Enter name"})
        assert result.is_error is False

    # Verify the progress callback was invoked
    assert len(progress_updates) == 1
    assert progress_updates[0] == {"progress": 1.0, "total": 1.0, "message": "User responded"}
