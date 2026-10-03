import anyio

from mcp import Client
from mcp.client.subscriptions import Subscription

from .tutorial003 import BOARD, read_board


async def watch(client: Client, sub: Subscription) -> None:
    async for _event in sub:
        board = await read_board(client)
        print(board)
        if "[ ]" not in board:
            return  # sprint finished: the stream closes when run_sprint leaves the block


async def run_sprint(client: Client) -> None:
    async with client.listen(resource_subscriptions=[BOARD]) as sub:
        print(await read_board(client))  # snapshot: acknowledged, so nothing after this is missed
        async with anyio.create_task_group() as tg:
            tg.start_soon(watch, client, sub)
            for task in ("design", "build", "ship"):
                await client.call_tool("complete_task", {"board": "sprint", "task": task})


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        await run_sprint(client)


if __name__ == "__main__":
    anyio.run(main)
