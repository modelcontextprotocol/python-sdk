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


@mcp.tool()
async def reserve_book(title: str, stock: Annotated[Stock, Resolve(check_stock)]) -> str:
    """Reserve a copy of a book."""
    if stock.copies == 0:
        return f"{title!r} is out of stock."
    return f"Reserved {title!r} ({stock.copies - 1} copies left)."
