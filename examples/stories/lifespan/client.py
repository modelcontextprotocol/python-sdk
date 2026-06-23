"""Prove the lifespan-yielded state is reachable from a tool call."""

from mcp.client import Client
from mcp.types import TextContent
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["lookup"]

    result = await client.call_tool("lookup", {"key": "alpha"})
    assert isinstance(result.content[0], TextContent) and result.content[0].text == "one", result

    result = await client.call_tool("lookup", {"key": "beta"})
    assert isinstance(result.content[0], TextContent) and result.content[0].text == "two", result


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
