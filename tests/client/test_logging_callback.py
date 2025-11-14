from typing import Any, Literal

import pytest

import mcp.types as types
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
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

    @server.tool("test_tool_with_log_extra")
    async def test_tool_with_log_extra(
        message: str,
        level: Literal["debug", "info", "warning", "error"],
        logger: str,
        extra_string: str,
        extra_dict: dict[str, Any],
    ) -> bool:
        """Send a log notification to the client with extra fields."""
        await server.get_context().log(
            level=level,
            message=message,
            logger_name=logger,
            extra={"extra_string": extra_string, "extra_dict": extra_dict},
        )
        return True

    # Create a message handler to catch exceptions
    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        logging_callback=logging_collector,
        message_handler=message_handler,
    ) as client_session:
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
        log_result_with_extra = await client_session.call_tool(
            "test_tool_with_log_extra",
            {
                "message": "Test log message",
                "level": "info",
                "logger": "test_logger",
                "extra_string": "example",
                "extra_dict": {"a": 1, "b": 2, "c": 3},
            },
        )
        assert log_result.isError is False
        assert log_result_with_extra.isError is False
        assert len(logging_collector.log_messages) == 2
        # Create meta object with related_request_id added dynamically
        log = logging_collector.log_messages[0]
        assert log.level == "info"
        assert log.logger == "test_logger"
        assert log.data == "Test log message"

        log_with_extra = logging_collector.log_messages[1]
        assert log_with_extra.level == "info"
        assert log_with_extra.logger == "test_logger"
        assert log_with_extra.data == {
            "message": "Test log message",
            "extra_string": "example",
            "extra_dict": {"a": 1, "b": 2, "c": 3},
        }
