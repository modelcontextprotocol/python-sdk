"""
Tests for custom notification handlers in ClientSession.

This module tests both workflows for handling custom/unknown notifications:
1. Generic unknown notification handler (fallback)
2. Type-specific custom notification handlers (registry)
"""

from typing import Any

import pytest

import mcp.types as types
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.shared.session import RequestResponder


class UnknownNotificationCollector:
    """Collector for unknown/custom notifications."""

    def __init__(self) -> None:
        self.notifications: list[types.ServerNotification] = []

    async def __call__(self, notification: types.ServerNotification) -> None:
        """Collect unknown notifications."""
        self.notifications.append(notification)


@pytest.fixture
def unknown_collector() -> UnknownNotificationCollector:
    """Create a collector for unknown notifications."""
    return UnknownNotificationCollector()


@pytest.fixture
def message_handler() -> Any:
    """Message handler that re-raises exceptions."""

    async def handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    return handler


@pytest.mark.anyio
async def test_unknown_notification_callback_not_called_for_known_types(
    unknown_collector: UnknownNotificationCollector,
    message_handler: Any,
) -> None:
    """Test that the unknown notification handler is NOT called for known notification types."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    # Register a tool that sends a known notification (logging)
    @server.tool("send_logging")
    async def send_logging_tool() -> bool:
        """Send a logging notification to the client."""
        # Logging notifications are handled by the specific logging_callback,
        # not the unknown_notification_callback
        return True

    async with create_session(
        server._mcp_server,
        unknown_notification_callback=unknown_collector,
        message_handler=message_handler,
    ) as client_session:
        # Call the tool
        result = await client_session.call_tool("send_logging", {})
        assert result.isError is False

        # The unknown notification collector should NOT have been called
        # because logging is a known notification type
        assert len(unknown_collector.notifications) == 0


@pytest.mark.anyio
async def test_custom_notification_handler_takes_priority(
    unknown_collector: UnknownNotificationCollector,
    message_handler: Any,
) -> None:
    """Test that custom notification handlers are checked before unknown handler."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    # Track which handler was called
    custom_handler_called: list[str] = []

    async def custom_handler(notification: types.ServerNotification) -> None:
        """Custom handler for a specific notification method."""
        custom_handler_called.append(notification.root.method)

    # Register a custom handler for a specific notification method
    custom_handlers = {
        "notifications/custom/test": custom_handler,
    }

    @server.tool("trigger_notification")
    async def trigger_tool() -> bool:
        """Tool that returns success."""
        return True

    async with create_session(
        server._mcp_server,
        custom_notification_handlers=custom_handlers,
        unknown_notification_callback=unknown_collector,
        message_handler=message_handler,
    ) as client_session:
        # Call the tool
        result = await client_session.call_tool("trigger_notification", {})
        assert result.isError is False

        # Neither handler should have been called for known notification types
        assert len(custom_handler_called) == 0
        assert len(unknown_collector.notifications) == 0


@pytest.mark.anyio
async def test_unknown_notification_callback_with_default(
    message_handler: Any,
) -> None:
    """Test that the default unknown notification callback does nothing."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    @server.tool("test_tool")
    async def test_tool() -> bool:
        """Simple test tool."""
        return True

    # Don't pass an unknown_notification_callback - use the default
    async with create_session(
        server._mcp_server,
        message_handler=message_handler,
    ) as client_session:
        # This should work fine with the default handler
        result = await client_session.call_tool("test_tool", {})
        assert result.isError is False


@pytest.mark.anyio
async def test_custom_handlers_empty_dict(
    unknown_collector: UnknownNotificationCollector,
    message_handler: Any,
) -> None:
    """Test that an empty custom handlers dict works correctly."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    @server.tool("test_tool")
    async def test_tool() -> bool:
        """Simple test tool."""
        return True

    # Pass an empty custom handlers dict
    async with create_session(
        server._mcp_server,
        custom_notification_handlers={},
        unknown_notification_callback=unknown_collector,
        message_handler=message_handler,
    ) as client_session:
        result = await client_session.call_tool("test_tool", {})
        assert result.isError is False

        # No unknown notifications should have been received
        assert len(unknown_collector.notifications) == 0


@pytest.mark.anyio
async def test_multiple_custom_handlers(
    message_handler: Any,
) -> None:
    """Test that multiple custom notification handlers can be registered."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    # Track which handlers were called
    handler_calls: dict[str, int] = {}

    async def create_custom_handler(name: str) -> Any:
        """Factory function to create a custom handler."""

        async def handler(notification: types.ServerNotification) -> None:
            handler_calls[name] = handler_calls.get(name, 0) + 1

        return handler

    # Register multiple custom handlers
    custom_handlers = {
        "notifications/custom/type1": await create_custom_handler("type1"),
        "notifications/custom/type2": await create_custom_handler("type2"),
        "notifications/custom/type3": await create_custom_handler("type3"),
    }

    @server.tool("test_tool")
    async def test_tool() -> bool:
        """Simple test tool."""
        return True

    async with create_session(
        server._mcp_server,
        custom_notification_handlers=custom_handlers,
        message_handler=message_handler,
    ) as client_session:
        result = await client_session.call_tool("test_tool", {})
        assert result.isError is False

        # No handlers should have been called yet (no matching notifications)
        assert len(handler_calls) == 0
