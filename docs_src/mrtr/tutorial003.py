from mcp_types import ElicitRequestParams, ElicitResult

from mcp import Client
from mcp.client import ClientRequestContext


async def handle_elicitation(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    return ElicitResult(action="accept", content={"region": "eu-west-1"})


async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp", elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("provision", {"name": "orders"})
        print(result.content)
