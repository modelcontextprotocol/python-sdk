import anyio

from mcp import Client
from mcp.client.subscriptions import SubscriptionLost

from .tutorial003 import read_board


async def keep_following(client: Client) -> None:
    while True:
        try:
            async with client.listen(resource_subscriptions=["board://sprint"]) as sub:
                print(await read_board(client))  # refetch: no replay across streams
                async for _event in sub:
                    print(await read_board(client))
        except SubscriptionLost:
            pass
        # Either ending means the stream is gone. Back off before re-listening:
        # a graceful close may be the server shedding load.
        await anyio.sleep(1)
