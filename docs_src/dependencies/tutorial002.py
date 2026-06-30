from typing import Annotated

from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver import RequestStateSecurity, Resolve

mcp = MCPServer("Bookshop", request_state_security=RequestStateSecurity.ephemeral())

INVENTORY = {"Dune": 7, "Neuromancer": 0}


class Stock(BaseModel):
    title: str
    copies: int


async def check_stock(title: str) -> Stock:
    return Stock(title=title, copies=INVENTORY.get(title, 0))


async def estimate_delivery(stock: Annotated[Stock, Resolve(check_stock)]) -> str:
    return "tomorrow" if stock.copies > 0 else "in 2-3 weeks"


@mcp.tool()
async def order_book(
    title: str,
    stock: Annotated[Stock, Resolve(check_stock)],
    delivery: Annotated[str, Resolve(estimate_delivery)],
) -> str:
    """Order a book from the shop."""
    if stock.copies == 0:
        return f"{title!r} is on backorder; it would arrive {delivery}."
    return f"Ordered {title!r}; it arrives {delivery}."
