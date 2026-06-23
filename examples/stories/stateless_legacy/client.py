"""Connect at each era; the same stateless app answers both with the same result."""

from mcp.client import Client
from mcp.shared.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from mcp.types import TextContent
from stories._harness import Connect, connect_from_args, run_client


async def scenario(client: Client, connect: Connect) -> None:
    # ── modern leg: the harness-supplied client connected at mode="auto"; the entry routed
    # this request through the 2026 envelope path. No initialize handshake, no session id.
    assert client.protocol_version == LATEST_MODERN_VERSION

    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["greet"]

    result = await client.call_tool("greet", {"name": "world"})
    assert not result.is_error
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Hello, world!", result

    # ── legacy leg: a fresh mode="legacy" client runs the initialize handshake against the
    # SAME stateless app. It is answered statelessly (no Mcp-Session-Id) and the same tool
    # gives the same answer — the era is invisible to the server body.
    async with connect(mode="legacy") as legacy:
        assert legacy.protocol_version == LATEST_HANDSHAKE_VERSION

        result = await legacy.call_tool("greet", {"name": "world"})
        assert not result.is_error
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello, world!", result


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), needs_connect=True, mode="auto")
