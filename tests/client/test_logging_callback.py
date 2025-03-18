from typing import List, Literal

import anyio
import pytest

from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.types import (
    LoggingMessageNotificationParams,
    TextContent,
)


class LoggingCollector:
    def __init__(self):
        self.log_messages: List[LoggingMessageNotificationParams] = []

    async def __call__(self, params: LoggingMessageNotificationParams) -> None:
        self.log_messages.append(params)


@pytest.mark.anyio
async def test_logging_callback():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")
    logging_collector = LoggingCollector()

    # Create a simple test tool
    @server.tool("test_tool")
    async def test_tool() -> bool:
        # The actual tool is very simple and just returns True
        return True

    # Create a function that can send a log notification
    @server.tool("test_tool_with_log")
    async def test_tool_with_log(
        message: str, level: Literal["debug", "info", "warning", "error"], logger: str
    ) -> bool:
        """Send a log notification to the client."""
        await server.get_context().log(
            level=level,
            message=message,
            logger_name=logger,
        )
        return True

    async with anyio.create_task_group() as tg:
        async with create_session(
            server._mcp_server, logging_callback=logging_collector
        ) as client_session:

            async def listen_session():
                try:
                    async for message in client_session.incoming_messages:
                        if isinstance(message, Exception):
                            raise message
                except anyio.EndOfStream:
                    pass

            tg.start_soon(listen_session)

            # First verify our test tool works
            result = await client_session.call_tool("test_tool", {})
            assert result.isError is False
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "true"

            # Now send a log message via our tool
            log_result = await client_session.call_tool(
                "test_tool_with_log",
                {
                    "message": "Test log message",
                    "level": "info",
                    "logger": "test_logger",
                },
            )
            assert log_result.isError is False
            assert len(logging_collector.log_messages) == 1
            assert logging_collector.log_messages[
                0
            ] == LoggingMessageNotificationParams(
                level="info", logger="test_logger", data="Test log message"
            )
