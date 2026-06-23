"""Connect to the sub-mounted MCP endpoint at /api, list tools and call greet."""

from mcp.client import Client
from mcp.types import TextContent
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["greet"]

    result = await client.call_tool("greet", {"name": "Starlette"})
    assert not result.is_error
    first = result.content[0]
    assert isinstance(first, TextContent)
    assert "Hello, Starlette!" in first.text, result
    assert result.structured_content == {"result": "Hello, Starlette! (served from a Starlette sub-mount)"}


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
