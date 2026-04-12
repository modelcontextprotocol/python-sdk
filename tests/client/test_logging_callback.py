from typing import Any, Literal

import pytest

from mcp import Client, types
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.session import RequestResponder
from mcp.types import (
    LoggingMessageNotificationParams,
    TextContent,
)


class LoggingCollector:
    def __init__(self):
        self.log_messages: list[LoggingMessageNotificationParams] = []

    async def __call__(self, params: LoggingMessageNotificationParams) -> None:
        self.log_messages.append(params)


@pytest.mark.anyio
async def test_logging_callback():
    server = MCPServer("test")
    logging_collector = LoggingCollector()

    # Create a simple test tool
    @server.tool("test_tool")
    async def test_tool() -> bool:
        # The actual tool is very simple and just returns True
        return True

    # Create a function that can send a log notification with a string
    @server.tool("test_tool_with_log")
    async def test_tool_with_log(
        message: str, level: Literal["debug", "info", "warning", "error"], logger: str, ctx: Context
    ) -> bool:
        """Send a log notification to the client."""
        await ctx.log(level=level, data=message, logger_name=logger)
        return True

    # Create a function that can send structured data as a log notification
    @server.tool("test_tool_with_structured_log")
    async def test_tool_with_structured_log(
        level: Literal["debug", "info", "warning", "error"],
        logger: str,
        ctx: Context,
    ) -> bool:
        """Send a structured log notification to the client."""
        await ctx.log(
            level=level,
            data={"message": "Test log message", "count": 42, "tags": ["a", "b"]},
            logger_name=logger,
        )
        return True

    # Create a message handler to catch exceptions
    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with Client(
        server,
        logging_callback=logging_collector,
        message_handler=message_handler,
    ) as client:
        # First verify our test tool works
        result = await client.call_tool("test_tool", {})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

        # Now send a string log message via our tool
        log_result = await client.call_tool(
            "test_tool_with_log",
            {
                "message": "Test log message",
                "level": "info",
                "logger": "test_logger",
            },
        )
        # Send a structured log message
        log_result_structured = await client.call_tool(
            "test_tool_with_structured_log",
            {
                "level": "info",
                "logger": "test_logger",
            },
        )
        assert log_result.is_error is False
        assert log_result_structured.is_error is False
        assert len(logging_collector.log_messages) == 2

        # Verify string log
        log = logging_collector.log_messages[0]
        assert log.level == "info"
        assert log.logger == "test_logger"
        assert log.data == "Test log message"

        # Verify structured log
        log_structured = logging_collector.log_messages[1]
        assert log_structured.level == "info"
        assert log_structured.logger == "test_logger"
        assert log_structured.data == {
            "message": "Test log message",
            "count": 42,
            "tags": ["a", "b"],
        }
