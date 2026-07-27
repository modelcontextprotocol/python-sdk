"""Connect to the same server factory twice — once per era, so `main` takes `targets` — and assert both are served."""

import mcp_types as types
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from mcp.client import Client
from stories._harness import TargetFactory, run_client


async def main(targets: TargetFactory, *, mode: str = "auto") -> None:
    # ── modern arm: the caller's mode (the real-user "auto" default) probes
    # ``server/discover`` and adopts the result — no ``initialize`` handshake runs.
    # The version/info/capabilities accessors are era-neutral.
    async with Client(targets(), mode=mode) as modern:
        assert modern.protocol_version == LATEST_MODERN_VERSION
        # On the 2026 era, server identity is an optional serverInfo stamp in the
        # result _meta (None for an anonymous server); this server stamps it.
        info = modern.server_info
        assert info is not None, "the server stamps serverInfo into its results"
        assert info.name == "dual-era-example"
        assert modern.server_capabilities.tools is not None

        listed = await modern.list_tools()
        assert [t.name for t in listed.tools] == ["greet"]

        result = await modern.call_tool("greet", {"name": "2026 client"})
        first = result.content[0]
        assert isinstance(first, types.TextContent)
        assert first.text == f"Hello, 2026 client! (served on the modern era at {LATEST_MODERN_VERSION})"

    # ── legacy arm: a fresh connection to the SAME server, pinned to the handshake era.
    # The same accessors are populated identically — here by ``initialize``.
    async with Client(targets(), mode="legacy") as legacy:
        assert legacy.protocol_version == LATEST_HANDSHAKE_VERSION
        info = legacy.server_info
        assert info is not None, "initialize always carries serverInfo"
        assert info.name == "dual-era-example"
        assert legacy.server_capabilities.tools is not None

        result = await legacy.call_tool("greet", {"name": "2025 client"})
        first = result.content[0]
        assert isinstance(first, types.TextContent)
        assert first.text == f"Hello, 2025 client! (served on the legacy era at {LATEST_HANDSHAKE_VERSION})"


if __name__ == "__main__":
    run_client(main)
