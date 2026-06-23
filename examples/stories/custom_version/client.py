"""Assert the client and server agree on the negotiated protocol version."""

from mcp import types
from mcp.client import Client
from mcp.shared.version import HANDSHAKE_PROTOCOL_VERSIONS
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    # Era-neutral accessor: populated from InitializeResult under mode="legacy".
    assert client.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS, client.protocol_version

    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["protocol_info"]

    result = await client.call_tool("protocol_info", {})
    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == client.protocol_version, result


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
