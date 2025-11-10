# Snippets demonstrating handling known and custom server notifications

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ServerNotification

# Create dummy server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",
    args=["run"],
    env={},
)


# Create a custom handler for the resource list changed notification
async def custom_resource_list_changed_handler() -> None:
    """Custom handler for resource list changed notifications."""
    print("RESOURCE LIST CHANGED")


# Create a fallback handler for custom notifications we aren't aware of.
async def fallback_notification_handler(notification: ServerNotification) -> None:
    """Fallback handler for unknown notifications."""
    print(f"UNKNOWN notification caught: {notification.root.method}")


async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read,
            write,
            resource_list_changed_callback=custom_resource_list_changed_handler,
            unknown_notification_callback=fallback_notification_handler,
        ) as session:
            # Initialize the connection
            await session.initialize()

            # Do client stuff here


if __name__ == "__main__":
    asyncio.run(run())
