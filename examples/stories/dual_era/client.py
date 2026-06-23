"""Connect to the same server factory twice — once per era — and assert both are served."""

from mcp import types
from mcp.client import Client
from mcp.shared.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from stories._harness import Connect, connect_from_args, run_client


async def scenario(client: Client, connect: Connect) -> None:
    # ── modern leg: the harness-supplied client connected at mode="auto", so __aenter__
    # sent server/discover and adopted the result — no initialize handshake ran.
    assert client.protocol_version == LATEST_MODERN_VERSION
    assert client.server_info.name == "dual-era-example"
    assert client.server_capabilities.tools is not None

    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["greet"]

    result = await client.call_tool("greet", {"name": "2026 client"})
    first = result.content[0]
    assert isinstance(first, types.TextContent)
    assert first.text == f"Hello, 2026 client! (served on the modern era at {LATEST_MODERN_VERSION})"

    # ── legacy leg: a fresh client at mode="legacy" runs the initialize handshake against
    # the SAME server factory. The era-neutral accessors are populated identically.
    async with connect(mode="legacy") as legacy:
        assert legacy.protocol_version == LATEST_HANDSHAKE_VERSION
        assert legacy.server_info.name == "dual-era-example"
        assert legacy.server_capabilities.tools is not None

        result = await legacy.call_tool("greet", {"name": "2025 client"})
        first = result.content[0]
        assert isinstance(first, types.TextContent)
        assert first.text == f"Hello, 2025 client! (served on the legacy era at {LATEST_HANDSHAKE_VERSION})"


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), needs_connect=True, mode="auto")
