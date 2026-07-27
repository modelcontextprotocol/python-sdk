from typing import Annotated

from mcp_types import ElicitRequestParams, ElicitResult
from pydantic import BaseModel

from mcp import Client
from mcp.client import ClientRequestContext
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


async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    return ElicitResult(action="accept", content={"copies": 2})


async def main() -> None:
    async with (
        Client(mcp, mode="legacy", elicitation_callback=answer) as legacy,
        Client(mcp, elicitation_callback=answer) as modern,
    ):
        for client in (legacy, modern):
            result = await client.call_tool("reserve", {"title": "Dune"})
            print(client.protocol_version, result.structured_content)
