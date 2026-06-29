"""Connect at each era — two connections, so `main` takes `targets`; the same stateless app answers both."""

from mcp_types import TextContent
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from mcp.client import Client
from stories._harness import TargetFactory, run_client


async def main(targets: TargetFactory, *, mode: str = "auto") -> None:
    # Modern era: the caller's mode (default "auto") takes the 2026 envelope path — no handshake, no session id.
    async with Client(targets(), mode=mode) as client:
        assert client.protocol_version == LATEST_MODERN_VERSION

        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == ["greet"]

        result = await client.call_tool("greet", {"name": "world"})
        assert not result.is_error
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello, world!", result

    # Legacy era: a fresh mode="legacy" client runs the initialize handshake against the SAME app,
    # answered statelessly (no Mcp-Session-Id); the era is invisible to the server body.
    async with Client(targets(), mode="legacy") as legacy:
        assert legacy.protocol_version == LATEST_HANDSHAKE_VERSION

        result = await legacy.call_tool("greet", {"name": "world"})
        assert not result.is_error
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello, world!", result


if __name__ == "__main__":
    run_client(main)
