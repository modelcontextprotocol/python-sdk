"""Prove the lifespan-yielded state is reachable from a tool call."""

from mcp_types import TextContent

from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == ["lookup"]

        result = await client.call_tool("lookup", {"key": "alpha"})
        assert isinstance(result.content[0], TextContent) and result.content[0].text == "one", result

        result = await client.call_tool("lookup", {"key": "beta"})
        assert isinstance(result.content[0], TextContent) and result.content[0].text == "two", result


if __name__ == "__main__":
    run_client(main)
