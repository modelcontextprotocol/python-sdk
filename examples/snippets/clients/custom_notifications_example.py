"""
Example demonstrating how to handle custom server notifications in MCP clients.

This example shows multiple workflows:
1. Overriding standard MCP notification handlers (logging, progress, etc.)
2. Registering custom notification handlers by method name
3. Generic handler for any unknown notification type (fallback)

The key feature demonstrated is custom_notification_handlers, which allows you to
register handlers for specific notification methods that your application defines.
"""

import asyncio
from typing import Any, Literal

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

# Create a FastMCP server that sends various notifications
server = FastMCP("Notification Demo Server")


@server.tool("send_logging_notification")
async def send_log(message: str, level: Literal["debug", "info", "warning", "error"]) -> str:
    """Sends a logging notification to demonstrate known notification handling."""
    await server.get_context().log(level=level, message=message, logger_name="demo")
    return f"Sent {level} log: {message}"


@server.tool("send_progress_notification")
async def send_progress(progress: float, total: float, message: str) -> str:
    """Sends a progress notification to demonstrate known notification handling."""
    ctx = server.get_context()
    if ctx.request_context.meta and ctx.request_context.meta.progressToken:
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_context.meta.progressToken,
            progress=progress,
            total=total,
            message=message,
        )
        return f"Sent progress: {progress}/{total} - {message}"
    return "No progress token provided"


@server.tool("trigger_resource_list_change")
async def trigger_resource_change() -> str:
    """Sends a resource list changed notification."""
    await server.get_context().session.send_resource_list_changed()
    return "Sent resource list changed notification"


def create_notification_handlers() -> tuple[Any, Any, Any, Any, list[dict[str, Any]]]:
    """Create notification handlers that share a common log."""
    notifications_log: list[dict[str, Any]] = []

    async def unknown_notification_handler(notification: types.ServerNotification) -> None:
        """Handler for unknown/custom notifications."""
        print(f"UNKNOWN notification caught: {notification.root.method}")
        notifications_log.append({"type": "unknown", "method": notification.root.method})

    async def custom_logging_handler(params: types.LoggingMessageNotificationParams) -> None:
        """Custom handler for logging notifications."""
        print(f"LOG (custom handler): [{params.level}] {params.data}")
        notifications_log.append({"type": "logging", "level": params.level, "message": params.data})

    async def custom_progress_handler(params: types.ProgressNotificationParams) -> None:
        """Custom handler for progress notifications."""
        print(f"PROGRESS: {params.progress}/{params.total} - {params.message or 'No message'}")
        notifications_log.append({"type": "progress", "progress": params.progress, "total": params.total})

    async def custom_resource_list_changed_handler() -> None:
        """Custom handler for resource list changed notifications."""
        print("RESOURCE LIST CHANGED")
        notifications_log.append({"type": "resource_list_changed"})

    return (
        unknown_notification_handler,
        custom_logging_handler,
        custom_progress_handler,
        custom_resource_list_changed_handler,
        notifications_log,
    )


async def example_1_override_standard_handlers() -> None:
    """Example 1: Override standard MCP notification handlers."""
    print("\n" + "=" * 70)
    print("Example 1: Using Custom Handlers for Known Notification Types")
    print("=" * 70)
    print("\nWe're overriding the default handlers with custom ones.\n")

    # Create handlers for example 1
    (
        _,  # unknown_handler not used in this example
        logging_handler,
        progress_handler,
        resource_handler,
        notifications_log,
    ) = create_notification_handlers()

    async with create_connected_server_and_client_session(
        server,
        logging_callback=logging_handler,
        progress_notification_callback=progress_handler,
        resource_list_changed_callback=resource_handler,
    ) as client:
        print("Client connected with custom notification handlers\n")

        # Send various notifications
        print("Sending logging notification...")
        result1 = await client.call_tool(
            "send_logging_notification", {"message": "Hello from server!", "level": "info"}
        )
        print(f"  Tool returned: {result1.content[0].text}\n")  # type: ignore[attr-defined]

        await asyncio.sleep(0.1)  # Give notifications time to process

        print("Sending progress notification...")
        result2 = await client.call_tool(
            "send_progress_notification",
            {"progress": 75.0, "total": 100.0, "message": "Processing..."},
            meta={"progressToken": "demo-token"},
        )
        print(f"  Tool returned: {result2.content[0].text}\n")  # type: ignore[attr-defined]

        await asyncio.sleep(0.1)

        print("Sending resource list changed notification...")
        result3 = await client.call_tool("trigger_resource_list_change", {})
        print(f"  Tool returned: {result3.content[0].text}\n")  # type: ignore[attr-defined]

        await asyncio.sleep(0.1)

    print(f"\nTotal notifications handled: {len(notifications_log)}")
    print("\nNotifications received:")
    for i, notif in enumerate(notifications_log, 1):
        print(f"  {i}. {notif}")


async def example_2_custom_notification_handlers() -> None:
    """Example 2: Register handlers for custom notification types by method name."""
    print("\n" + "=" * 70)
    print("Example 2: Custom Notification Handlers by Method Name")
    print("=" * 70)
    print("\nThis shows how to register handlers for SPECIFIC custom notification")
    print("types that your application defines. These handlers are checked FIRST,")
    print("before the standard notification types.\n")

    # Define handlers for specific custom notification methods
    custom_notifications_received: list[dict[str, Any]] = []

    async def analytics_notification_handler(notification: types.ServerNotification) -> None:
        """Handler for custom analytics notifications from our app."""
        print(f"ANALYTICS notification: {notification.root.method}")
        custom_notifications_received.append(
            {
                "handler": "analytics",
                "method": notification.root.method,
                "data": notification.root,
            }
        )

    async def telemetry_notification_handler(notification: types.ServerNotification) -> None:
        """Handler for custom telemetry notifications from our app."""
        print(f"TELEMETRY notification: {notification.root.method}")
        custom_notifications_received.append(
            {
                "handler": "telemetry",
                "method": notification.root.method,
                "data": notification.root,
            }
        )

    async def custom_app_notification_handler(notification: types.ServerNotification) -> None:
        """Handler for general custom app notifications."""
        print(f"CUSTOM APP notification: {notification.root.method}")
        custom_notifications_received.append(
            {
                "handler": "custom_app",
                "method": notification.root.method,
                "data": notification.root,
            }
        )

    # Register custom handlers by their notification method names
    # In a real app, your server would send notifications with these method names
    custom_handlers = {
        "notifications/custom/analytics": analytics_notification_handler,
        "notifications/custom/telemetry": telemetry_notification_handler,
        "notifications/custom/myapp/status": custom_app_notification_handler,
        "notifications/custom/myapp/alert": custom_app_notification_handler,
    }

    print("Custom notification handlers registered for:")
    for method in custom_handlers:
        print(f"  • {method}")

    # Also create an unknown handler as fallback
    (unknown_handler2, _, _, _, _) = create_notification_handlers()

    async with create_connected_server_and_client_session(
        server,
        custom_notification_handlers=custom_handlers,
        unknown_notification_callback=unknown_handler2,
    ) as client:
        print("\nClient connected with custom notification handlers")
        print("\nIn a real application:")
        print("  • Your server sends notifications with method names like")
        print("    'notifications/custom/analytics'")
        print("  • The client automatically routes them to the registered handlers")
        print("  • Unknown notifications fall back to the unknown_notification_callback")
        print("\nFor this demo, we'll just call a regular tool since we can't easily")
        print("send truly custom notifications from FastMCP without extending the protocol.\n")

        await client.call_tool("send_logging_notification", {"message": "Regular operation", "level": "info"})
        await asyncio.sleep(0.1)

    print(f"\nCustom notification handlers ready: {len(custom_handlers)} registered")
    print(f"Custom notifications received: {len(custom_notifications_received)}")
    print("\nExample usage in your own code:")
    print("""
    # Server side (in your MCP server):
    await session.send_notification(
        ServerNotification(
            root=Notification(
                method="notifications/custom/analytics",
                params={"event": "user_action", "data": {...}}
            )
        )
    )

    # Client side (this file):
    custom_handlers = {
        "notifications/custom/analytics": your_analytics_handler,
    }
    """)


async def example_3_unknown_notification_fallback() -> None:
    """Example 3: Unknown notification fallback handler."""
    print("\n" + "=" * 70)
    print("Example 3: Unknown Notification Fallback (Conceptual)")
    print("=" * 70)
    print("\nThe unknown_notification_callback catches any notification that")
    print("doesn't match registered custom handlers OR known MCP types.")
    print("\nThis example shows that KNOWN notifications are NOT sent to the")
    print("unknown handler - they go to their specific handlers instead.\n")

    # Create handlers for example 3
    (
        unknown_handler3,
        logging_handler3,
        _,
        _,
        notifications_log3,
    ) = create_notification_handlers()

    async with create_connected_server_and_client_session(
        server,
        unknown_notification_callback=unknown_handler3,
        logging_callback=logging_handler3,
    ) as client:
        print("Client connected with unknown notification fallback handler\n")

        print("Sending a standard logging notification (a KNOWN type)...")
        result = await client.call_tool(
            "send_logging_notification", {"message": "This uses the custom handler", "level": "debug"}
        )
        print(f"  Tool returned: {result.content[0].text}\n")  # type: ignore[attr-defined]

        await asyncio.sleep(0.1)

    print(f"\nKnown notifications (logging): {len([n for n in notifications_log3 if n['type'] == 'logging'])}")
    print(f"Unknown notifications: {len([n for n in notifications_log3 if n['type'] == 'unknown'])}")
    print("\n✓ The known notification was handled by the logging_callback,")
    print("  NOT by the unknown_notification_callback (as expected!)")
    print("\nIn a real application with custom notification types:")
    print("  • Notifications like 'notifications/custom/myapp' would be")
    print("    sent to the unknown handler if not in custom_notification_handlers")
    print("  • Known MCP types (logging, progress, etc.) are never 'unknown'")


async def example_4_selective_override() -> None:
    """Example 4: Selective override of specific handlers."""
    print("\n" + "=" * 70)
    print("Example 4: Real-World Pattern - Selective Override")
    print("=" * 70)
    print("\nOverride only specific notification handlers while using defaults")
    print("for others. Perfect for production monitoring scenarios.\n")

    # Create handlers for example 4
    (
        _,
        logging_handler4,
        _,
        _,
        notifications_log4,
    ) = create_notification_handlers()

    # Only override logging, let other notifications use defaults
    async with create_connected_server_and_client_session(
        server,
        logging_callback=logging_handler4,  # Custom
        # progress_notification_callback uses default
        # resource_list_changed_callback uses default
    ) as client:
        print("Client connected with selective handler overrides\n")

        print("Sending multiple notifications...")
        await client.call_tool("send_logging_notification", {"message": "Custom handler!", "level": "warning"})
        await asyncio.sleep(0.05)

        await client.call_tool(
            "send_progress_notification",
            {"progress": 50.0, "total": 100.0, "message": "Default handler"},
            meta={"progressToken": "token-2"},
        )
        await asyncio.sleep(0.05)

        await client.call_tool("trigger_resource_list_change", {})
        await asyncio.sleep(0.1)

        print("")  # newline after notifications

    print(f"\nCustom-handled notifications: {len([n for n in notifications_log4 if n['type'] == 'logging'])}")
    print("Default-handled notifications: Progress and ResourceListChanged\n")


async def main() -> None:
    """Run all examples demonstrating custom notification handling."""
    print("=" * 70)
    print("MCP Custom Notification Handling Demo")
    print("=" * 70)

    # Run all examples
    await example_1_override_standard_handlers()
    await example_2_custom_notification_handlers()
    await example_3_unknown_notification_fallback()
    await example_4_selective_override()

    # Summary
    print("=" * 70)
    print("Demo Complete!")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("  1. Override standard MCP notification handlers (logging, progress, etc.)")
    print("  2. Register custom notification handlers by method name")
    print("     → Use custom_notification_handlers dict")
    print("     → These are checked FIRST, before standard types")
    print("  3. Unknown notification callback catches unrecognized types")
    print("     → Fallback for anything not in custom handlers or standard types")
    print("  4. Selectively override only the handlers you need")
    print("  5. Default handlers are used when no custom handler is provided")
    print("\nNotification Processing Order:")
    print("  1. Custom notification handlers (by method name)")
    print("  2. Standard MCP notification types")
    print("  3. Unknown notification callback (fallback)")


if __name__ == "__main__":
    asyncio.run(main())
