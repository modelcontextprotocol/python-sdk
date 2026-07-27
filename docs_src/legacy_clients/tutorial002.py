from typing import Annotated

from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver import AcceptedElicitation, Elicit, ElicitationResult, Resolve

mcp = MCPServer("Bookshop")


class Quantity(BaseModel):
    copies: int


async def ask_quantity() -> Elicit[Quantity]:
    """Resolver: ask the user how many copies to put aside."""
    return Elicit("How many copies?", Quantity)


@mcp.tool()
async def reserve(title: str, quantity: Annotated[ElicitationResult[Quantity], Resolve(ask_quantity)]) -> str:
    """Reserve copies of a book, asking the user how many."""
    if isinstance(quantity, AcceptedElicitation):
        return f"Reserved {quantity.data.copies} of {title!r}."
    return "Nothing reserved."


app = mcp.streamable_http_app(stateless_http=True)
