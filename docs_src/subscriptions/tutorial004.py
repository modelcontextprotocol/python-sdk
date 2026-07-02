import anyio

from mcp import Client
from mcp.client.subscriptions import SubscriptionLost


async def watch(client: Client, uri: str) -> None:
    """Keep one resource fresh for as long as the client lives."""
    while True:
        try:
            async with client.listen(resource_subscriptions=[uri]) as sub:
                await client.read_resource(uri)  # refetch: no replay across streams
                async for _event in sub:
                    await client.read_resource(uri)
        except SubscriptionLost:
            pass
        # Graceful close or abrupt drop, the stream is gone either way. Back
        # off before re-listening - a graceful close may be the server
        # shedding load, and reconnecting instantly recreates the pressure.
        await anyio.sleep(1)
