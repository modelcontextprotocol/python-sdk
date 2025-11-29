"""
Tests for client notification callbacks.

This module tests all notification types that can be sent from the server to the client,
ensuring that the callback mechanism works correctly for each notification type.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import AnyUrl

import mcp.types as types
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.shared.session import RequestResponder
from mcp.types import TextContent

if TYPE_CHECKING:
    from _pytest.fixtures import FixtureRequest


class ProgressNotificationCollector:
    """Collector for ProgressNotification events."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.notifications: list[types.ProgressNotificationParams] = []

    async def __call__(self, params: types.ProgressNotificationParams) -> None:
        """Collect a progress notification."""
        self.notifications.append(params)


class ResourceUpdatedCollector:
    """Collector for ResourceUpdatedNotification events."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.notifications: list[types.ResourceUpdatedNotificationParams] = []

    async def __call__(self, params: types.ResourceUpdatedNotificationParams) -> None:
        """Collect a resource updated notification."""
        self.notifications.append(params)


class ResourceListChangedCollector:
    """Collector for ResourceListChangedNotification events."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.notification_count: int = 0

    async def __call__(self) -> None:
        """Collect a resource list changed notification."""
        self.notification_count += 1


class ToolListChangedCollector:
    """Collector for ToolListChangedNotification events."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.notification_count: int = 0

    async def __call__(self) -> None:
        """Collect a tool list changed notification."""
        self.notification_count += 1


class PromptListChangedCollector:
    """Collector for PromptListChangedNotification events."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.notification_count: int = 0

    async def __call__(self) -> None:
        """Collect a prompt list changed notification."""
        self.notification_count += 1


class ElicitCompleteCollector:
    """Collector for ElicitCompleteNotification events."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.notifications: list[types.ElicitCompleteNotificationParams] = []

    async def __call__(self, params: types.ElicitCompleteNotificationParams) -> None:
        """Collect an elicit complete notification."""
        self.notifications.append(params)


@pytest.fixture
def progress_collector() -> ProgressNotificationCollector:
    """Create a progress notification collector."""
    return ProgressNotificationCollector()


@pytest.fixture
def resource_updated_collector() -> ResourceUpdatedCollector:
    """Create a resource updated collector."""
    return ResourceUpdatedCollector()


@pytest.fixture
def resource_list_changed_collector() -> ResourceListChangedCollector:
    """Create a resource list changed collector."""
    return ResourceListChangedCollector()


@pytest.fixture
def tool_list_changed_collector() -> ToolListChangedCollector:
    """Create a tool list changed collector."""
    return ToolListChangedCollector()


@pytest.fixture
def prompt_list_changed_collector() -> PromptListChangedCollector:
    """Create a prompt list changed collector."""
    return PromptListChangedCollector()


@pytest.fixture
def elicit_complete_collector() -> ElicitCompleteCollector:
    """Create an elicit complete collector."""
    return ElicitCompleteCollector()


@pytest.mark.anyio
async def test_progress_notification_callback(progress_collector: ProgressNotificationCollector) -> None:
    """Test that progress notifications are correctly received by the callback."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    @server.tool("send_progress")
    async def send_progress_tool(progress: float, total: float, message: str) -> bool:
        """Send a progress notification to the client."""
        # Get the progress token from the request metadata
        ctx = server.get_context()
        if ctx.request_context.meta and ctx.request_context.meta.progressToken:  # pragma: no branch
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_context.meta.progressToken,
                progress=progress,
                total=total,
                message=message,
            )
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        progress_notification_callback=progress_collector,
        message_handler=message_handler,
    ) as client_session:
        # Call tool with progress token in metadata
        result = await client_session.call_tool(
            "send_progress",
            {"progress": 50.0, "total": 100.0, "message": "Halfway there"},
            meta={"progressToken": "test-token-123"},
        )
        assert result.isError is False

        # Verify the progress notification was received
        assert len(progress_collector.notifications) == 1
        notification = progress_collector.notifications[0]
        assert notification.progressToken == "test-token-123"
        assert notification.progress == 50.0
        assert notification.total == 100.0
        assert notification.message == "Halfway there"


@pytest.mark.anyio
async def test_resource_updated_callback(resource_updated_collector: ResourceUpdatedCollector) -> None:
    """Test that resource updated notifications are correctly received by the callback."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    @server.tool("update_resource")
    async def update_resource_tool(uri: str) -> bool:
        """Send a resource updated notification to the client."""
        await server.get_context().session.send_resource_updated(AnyUrl(uri))
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        resource_updated_callback=resource_updated_collector,
        message_handler=message_handler,
    ) as client_session:
        # Trigger resource update notification
        result = await client_session.call_tool("update_resource", {"uri": "file:///test/resource.txt"})
        assert result.isError is False

        # Verify the notification was received
        assert len(resource_updated_collector.notifications) == 1
        notification = resource_updated_collector.notifications[0]
        assert str(notification.uri) == "file:///test/resource.txt"


@pytest.mark.anyio
async def test_resource_list_changed_callback(
    resource_list_changed_collector: ResourceListChangedCollector,
) -> None:
    """Test that resource list changed notifications are correctly received by the callback."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    @server.tool("change_resource_list")
    async def change_resource_list_tool() -> bool:
        """Send a resource list changed notification to the client."""
        await server.get_context().session.send_resource_list_changed()
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        resource_list_changed_callback=resource_list_changed_collector,
        message_handler=message_handler,
    ) as client_session:
        # Trigger resource list changed notification
        result = await client_session.call_tool("change_resource_list", {})
        assert result.isError is False

        # Verify the notification was received
        assert resource_list_changed_collector.notification_count == 1


@pytest.mark.anyio
async def test_tool_list_changed_callback(tool_list_changed_collector: ToolListChangedCollector) -> None:
    """Test that tool list changed notifications are correctly received by the callback."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    @server.tool("change_tool_list")
    async def change_tool_list_tool() -> bool:
        """Send a tool list changed notification to the client."""
        await server.get_context().session.send_tool_list_changed()
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        tool_list_changed_callback=tool_list_changed_collector,
        message_handler=message_handler,
    ) as client_session:
        # Trigger tool list changed notification
        result = await client_session.call_tool("change_tool_list", {})
        assert result.isError is False

        # Verify the notification was received
        assert tool_list_changed_collector.notification_count == 1


@pytest.mark.anyio
async def test_prompt_list_changed_callback(prompt_list_changed_collector: PromptListChangedCollector) -> None:
    """Test that prompt list changed notifications are correctly received by the callback."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    @server.tool("change_prompt_list")
    async def change_prompt_list_tool() -> bool:
        """Send a prompt list changed notification to the client."""
        await server.get_context().session.send_prompt_list_changed()
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        prompt_list_changed_callback=prompt_list_changed_collector,
        message_handler=message_handler,
    ) as client_session:
        # Trigger prompt list changed notification
        result = await client_session.call_tool("change_prompt_list", {})
        assert result.isError is False

        # Verify the notification was received
        assert prompt_list_changed_collector.notification_count == 1


@pytest.mark.anyio
async def test_elicit_complete_callback(elicit_complete_collector: ElicitCompleteCollector) -> None:
    """Test that elicit complete notifications are correctly received by the callback."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    @server.tool("send_elicit_complete")
    async def send_elicit_complete_tool(elicitation_id: str) -> bool:
        """Send an elicit complete notification to the client."""
        await server.get_context().session.send_elicit_complete(elicitation_id)
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with create_session(
        server._mcp_server,
        elicit_complete_callback=elicit_complete_collector,
        message_handler=message_handler,
    ) as client_session:
        # Trigger elicit complete notification
        result = await client_session.call_tool("send_elicit_complete", {"elicitation_id": "test-elicit-123"})
        assert result.isError is False

        # Verify the notification was received
        assert len(elicit_complete_collector.notifications) == 1
        notification = elicit_complete_collector.notifications[0]
        assert notification.elicitationId == "test-elicit-123"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "notification_type,callback_param,collector_fixture,tool_name,tool_args,verification",
    [
        (
            "progress",
            "progress_notification_callback",
            "progress_collector",
            "send_progress",
            {"progress": 75.0, "total": 100.0, "message": "Almost done"},
            lambda c: (  # type: ignore[misc]
                len(c.notifications) == 1  # type: ignore[attr-defined]
                and c.notifications[0].progress == 75.0  # type: ignore[attr-defined]
                and c.notifications[0].total == 100.0  # type: ignore[attr-defined]
                and c.notifications[0].message == "Almost done"  # type: ignore[attr-defined]
            ),
        ),
        (
            "resource_updated",
            "resource_updated_callback",
            "resource_updated_collector",
            "update_resource",
            {"uri": "file:///test/data.json"},
            lambda c: (  # type: ignore[misc]
                len(c.notifications) == 1  # type: ignore[attr-defined]
                and str(c.notifications[0].uri) == "file:///test/data.json"  # type: ignore[attr-defined]
            ),
        ),
        (
            "resource_list_changed",
            "resource_list_changed_callback",
            "resource_list_changed_collector",
            "change_resource_list",
            {},
            lambda c: c.notification_count == 1,  # type: ignore[attr-defined]
        ),
        (
            "tool_list_changed",
            "tool_list_changed_callback",
            "tool_list_changed_collector",
            "change_tool_list",
            {},
            lambda c: c.notification_count == 1,  # type: ignore[attr-defined]
        ),
        (
            "prompt_list_changed",
            "prompt_list_changed_callback",
            "prompt_list_changed_collector",
            "change_prompt_list",
            {},
            lambda c: c.notification_count == 1,  # type: ignore[attr-defined]
        ),
        (
            "elicit_complete",
            "elicit_complete_callback",
            "elicit_complete_collector",
            "send_elicit_complete",
            {"elicitation_id": "param-test-elicit-456"},
            lambda c: (  # type: ignore[misc]
                len(c.notifications) == 1  # type: ignore[attr-defined]
                and c.notifications[0].elicitationId == "param-test-elicit-456"  # type: ignore[attr-defined]
            ),
        ),
    ],
)
async def test_notification_callback_parametrized(
    notification_type: str,
    callback_param: str,
    collector_fixture: str,
    tool_name: str,
    tool_args: dict[str, Any],
    verification: Callable[[Any], bool],
    request: "FixtureRequest",
) -> None:
    """Parametrized test for all notification callbacks."""
    from mcp.server.fastmcp import FastMCP

    # Get the collector from the fixture
    collector = request.getfixturevalue(collector_fixture)

    server = FastMCP("test")

    # Define all tools (simpler than dynamic tool creation)
    @server.tool("send_progress")
    async def send_progress_tool(progress: float, total: float, message: str) -> bool:
        """Send a progress notification to the client."""
        ctx = server.get_context()
        if ctx.request_context.meta and ctx.request_context.meta.progressToken:  # pragma: no branch
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_context.meta.progressToken,
                progress=progress,
                total=total,
                message=message,
            )
        return True

    @server.tool("update_resource")
    async def update_resource_tool(uri: str) -> bool:
        """Send a resource updated notification to the client."""
        await server.get_context().session.send_resource_updated(AnyUrl(uri))
        return True

    @server.tool("change_resource_list")
    async def change_resource_list_tool() -> bool:
        """Send a resource list changed notification to the client."""
        await server.get_context().session.send_resource_list_changed()
        return True

    @server.tool("change_tool_list")
    async def change_tool_list_tool() -> bool:
        """Send a tool list changed notification to the client."""
        await server.get_context().session.send_tool_list_changed()
        return True

    @server.tool("change_prompt_list")
    async def change_prompt_list_tool() -> bool:
        """Send a prompt list changed notification to the client."""
        await server.get_context().session.send_prompt_list_changed()
        return True

    @server.tool("send_elicit_complete")
    async def send_elicit_complete_tool(elicitation_id: str) -> bool:
        """Send an elicit complete notification to the client."""
        await server.get_context().session.send_elicit_complete(elicitation_id)
        return True

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle exceptions from the session."""
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    # Create session with the appropriate callback
    session_kwargs: dict[str, Any] = {callback_param: collector, "message_handler": message_handler}

    async with create_session(server._mcp_server, **session_kwargs) as client_session:  # type: ignore[arg-type]
        # Call the appropriate tool
        meta = {"progressToken": "param-test-token"} if notification_type == "progress" else None
        result = await client_session.call_tool(tool_name, tool_args, meta=meta)
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

        # Verify using the provided verification function
        assert verification(collector), f"Verification failed for {notification_type}"


@pytest.mark.anyio
async def test_all_default_callbacks_with_notifications() -> None:
    """Test that all default notification callbacks work (they do nothing).

    This single test covers multiple default callbacks by not providing
    custom callbacks and triggering various notification types.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    @server.tool("send_progress")
    async def send_progress_tool(progress: float, total: float) -> bool:
        """Send a progress notification."""
        ctx = server.get_context()
        if ctx.request_context.meta and ctx.request_context.meta.progressToken:  # pragma: no branch
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_context.meta.progressToken,
                progress=progress,
                total=total,
            )
        return True

    @server.tool("send_resource_updated")
    async def send_resource_updated_tool(uri: str) -> bool:
        """Send a resource updated notification."""
        from pydantic import AnyUrl

        await server.get_context().session.send_resource_updated(uri=AnyUrl(uri))
        return True

    @server.tool("send_resource_list_changed")
    async def send_resource_list_changed_tool() -> bool:
        """Send a resource list changed notification."""
        await server.get_context().session.send_resource_list_changed()
        return True

    @server.tool("send_tool_list_changed")
    async def send_tool_list_changed_tool() -> bool:
        """Send a tool list changed notification."""
        await server.get_context().session.send_tool_list_changed()
        return True

    @server.tool("send_prompt_list_changed")
    async def send_prompt_list_changed_tool() -> bool:
        """Send a prompt list changed notification."""
        await server.get_context().session.send_prompt_list_changed()
        return True

    @server.tool("send_elicit_complete")
    async def send_elicit_complete_tool(elicitation_id: str) -> bool:
        """Send an elicit complete notification."""
        await server.get_context().session.send_elicit_complete(elicitation_id)
        return True

    # Create session WITHOUT custom callbacks - all will use defaults
    async with create_session(server._mcp_server) as client_session:
        # Test progress notification with default callback
        result1 = await client_session.call_tool(
            "send_progress",
            {"progress": 50.0, "total": 100.0},
            meta={"progressToken": "test-token"},
        )
        assert result1.isError is False

        # Test resource updated with default callback
        result2 = await client_session.call_tool(
            "send_resource_updated",
            {"uri": "file:///test.txt"},
        )
        assert result2.isError is False

        # Test resource list changed with default callback
        result3 = await client_session.call_tool("send_resource_list_changed", {})
        assert result3.isError is False

        # Test tool list changed with default callback
        result4 = await client_session.call_tool("send_tool_list_changed", {})
        assert result4.isError is False

        # Test prompt list changed with default callback
        result5 = await client_session.call_tool("send_prompt_list_changed", {})
        assert result5.isError is False

        # Test elicit complete with default callback
        result6 = await client_session.call_tool("send_elicit_complete", {"elicitation_id": "test-123"})
        assert result6.isError is False


@pytest.mark.anyio
async def test_progress_tool_without_progress_token() -> None:
    """Test progress tool when no progress token is provided in metadata."""
    from mcp.server.fastmcp import FastMCP

    progress_collector = ProgressNotificationCollector()
    server = FastMCP("test")

    @server.tool("send_progress")
    async def send_progress_tool(progress: float, total: float, message: str) -> bool:
        """Send a progress notification to the client."""
        ctx = server.get_context()
        # This branch: when meta is None or no progressToken
        if ctx.request_context.meta and ctx.request_context.meta.progressToken:  # pragma: no cover
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_context.meta.progressToken,
                progress=progress,
                total=total,
                message=message,
            )
        return True

    async with create_session(server._mcp_server, progress_notification_callback=progress_collector) as client_session:
        # Call without meta - takes the False branch
        result = await client_session.call_tool(
            "send_progress",
            {"progress": 50.0, "total": 100.0, "message": "test"},
        )
        assert result.isError is False
        # No notification should be sent when no progress token is provided
        assert len(progress_collector.notifications) == 0


@pytest.mark.anyio
async def test_parametrized_progress_tool_without_progress_token() -> None:
    """Test parametrized progress tool when no progress token is provided."""
    from mcp.server.fastmcp import FastMCP

    progress_collector = ProgressNotificationCollector()
    server = FastMCP("test")

    @server.tool("send_progress")
    async def send_progress_tool(progress: float, total: float, message: str) -> bool:
        """Send a progress notification to the client."""
        ctx = server.get_context()
        if ctx.request_context.meta and ctx.request_context.meta.progressToken:  # pragma: no cover
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_context.meta.progressToken,
                progress=progress,
                total=total,
                message=message,
            )
        return True

    async with create_session(server._mcp_server, progress_notification_callback=progress_collector) as client_session:
        # Call with empty meta dict - takes the False branch
        result = await client_session.call_tool(
            "send_progress",
            {"progress": 75.0, "total": 100.0, "message": "Almost done"},
            meta={},
        )
        assert result.isError is False
        # No notification should be sent when meta exists but has no progressToken
        assert len(progress_collector.notifications) == 0


@pytest.mark.anyio
async def test_default_callback_progress_tool_without_progress_token() -> None:
    """Test that default progress callback handles missing progress token correctly."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-server")

    @server.tool("send_progress")
    async def send_progress_tool(progress: float, total: float) -> bool:
        """Send a progress notification."""
        ctx = server.get_context()
        if ctx.request_context.meta and ctx.request_context.meta.progressToken:  # pragma: no cover
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_context.meta.progressToken,
                progress=progress,
                total=total,
            )
        return True

    async with create_session(server._mcp_server) as client_session:
        # Call without meta - the False branch is taken in the tool
        result = await client_session.call_tool(
            "send_progress",
            {"progress": 50.0, "total": 100.0},
        )
        assert result.isError is False
