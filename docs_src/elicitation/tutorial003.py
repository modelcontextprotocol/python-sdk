from mcp_types import ElicitRequestParams, ElicitRequestURLParams, ElicitResult

from mcp import Client
from mcp.client import ClientRequestContext


async def handle_elicitation(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    if isinstance(params, ElicitRequestURLParams):
        print(f"Open this link to continue: {params.url}")
        return ElicitResult(action="accept")
    print(params.message)
    return ElicitResult(action="accept", content={"accept_alternative": True, "date": "2025-12-27"})


async def main() -> None:
    async with Client(
        "http://127.0.0.1:8000/mcp",
        mode="legacy",
        elicitation_callback=handle_elicitation,
    ) as client:
        result = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
        print(result.content)
