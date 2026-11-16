import anyio

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")

holds: set[str] = set()


async def take_payment(title: str) -> None:
    await anyio.sleep(30)  # the customer is typing a card number


async def release_hold(title: str) -> None:
    await anyio.sleep(0.1)  # a round trip to the stock system
    holds.discard(title)


@mcp.tool()
async def order_book(title: str) -> str:
    """Hold a copy of a book while the customer pays for it."""
    holds.add(title)
    try:
        await take_payment(title)
        return f"Ordered {title!r}."
    finally:
        with anyio.move_on_after(5, shield=True):
            await release_hold(title)
