import anyio

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult


async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    return ElicitResult(action="accept", content={"copies": 2})


async def main() -> None:
    async with (
        Client("http://localhost:8000/mcp", mode="legacy", elicitation_callback=answer) as legacy,
        Client("http://localhost:8000/mcp", elicitation_callback=answer) as modern,
    ):
        for client in (legacy, modern):
            result = await client.call_tool("reserve", {"title": "Dune"})
            print(client.protocol_version, result.structured_content)


if __name__ == "__main__":
    anyio.run(main)
