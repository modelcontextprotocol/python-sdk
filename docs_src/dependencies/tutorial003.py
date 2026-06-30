from typing import Annotated

from pydantic import BaseModel, Field

from mcp.server import MCPServer
from mcp.server.mcpserver import Elicit, RequestStateSecurity, Resolve

mcp = MCPServer("Bookshop", request_state_security=RequestStateSecurity.ephemeral())

INVENTORY = {"Dune": 7, "Neuromancer": 0}


class Stock(BaseModel):
    title: str
    copies: int


class Backorder(BaseModel):
    confirm: bool = Field(description="Order anyway and wait?")


async def check_stock(title: str) -> Stock:
    return Stock(title=title, copies=INVENTORY.get(title, 0))


async def confirm_backorder(
    title: str,
    stock: Annotated[Stock, Resolve(check_stock)],
) -> Backorder | Elicit[Backorder]:
    if stock.copies > 0:
        return Backorder(confirm=True)  # in stock: nothing to ask
    return Elicit(f"{title!r} is out of stock (2-3 weeks). Order anyway?", Backorder)


@mcp.tool()
async def order_book(
    title: str,
    stock: Annotated[Stock, Resolve(check_stock)],
    backorder: Annotated[Backorder, Resolve(confirm_backorder)],
) -> str:
    """Order a book from the shop."""
    if not backorder.confirm:
        return "No order placed."
    if stock.copies == 0:
        return f"Backordered {title!r}; it ships in 2-3 weeks."
    return f"Ordered {title!r}."
