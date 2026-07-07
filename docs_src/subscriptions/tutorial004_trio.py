import trio

from mcp import Client
from mcp.client.subscriptions import Subscription

from .tutorial001 import mcp
from .tutorial003 import read_board


async def watch(client: Client, sub: Subscription) -> None:
    async for _event in sub:
        board = await read_board(client)
        print(board)
        if "[ ]" not in board:
            return  # sprint finished: the stream closes when main() leaves the block


async def main() -> None:
    async with Client(mcp) as client:
        async with client.listen(resource_subscriptions=["board://sprint"]) as sub:
            print(await read_board(client))  # snapshot: acknowledged, so nothing after this is missed
            async with trio.open_nursery() as nursery:
                nursery.start_soon(watch, client, sub)
                for task in ("design", "build", "ship"):
                    await client.call_tool("complete_task", {"board": "sprint", "task": task})


if __name__ == "__main__":
    trio.run(main)
