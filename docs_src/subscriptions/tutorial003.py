from mcp import Client
from mcp.client.subscriptions import ResourceUpdated

from .tutorial001 import mcp


async def watch_todo() -> str:
    """Wait for the todo note to change once, then stop listening."""
    async with Client(mcp) as client:
        async with client.listen(resource_subscriptions=["note://todo"]) as sub:
            async for event in sub:
                assert isinstance(event, ResourceUpdated)
                return f"changed: {event.uri}"
    return "the server closed the stream before any change"
