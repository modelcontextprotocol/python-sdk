"""Probe server/discover once, persist the DiscoverResult, then reconnect with zero round-trips."""

from typing import Any

import anyio

from mcp.client import Client
from mcp.shared.version import LATEST_MODERN_VERSION
from mcp.types import DiscoverResult
from stories._harness import Connect, connect_from_args, run_client

# The harness pins era="modern" → mode=LATEST_MODERN_VERSION (R8); override to "auto" so the
# first connection actually probes server/discover and caches the real DiscoverResult.
client_kw: dict[str, Any] = {"mode": "auto"}


async def scenario(client: Client, connect: Connect) -> None:
    # ── first connection: mode="auto" probed server/discover inside __aenter__ ──
    discovered = client.session.discover_result
    assert discovered is not None, "mode='auto' against a modern server populates discover_result"
    assert client.protocol_version == LATEST_MODERN_VERSION
    assert client.server_info.name == "reconnect-example"
    assert LATEST_MODERN_VERSION in discovered.supported_versions

    result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"result": 5}, result

    # ── persist: round-trip through JSON to model loading from a cache on disk ──
    saved = discovered.model_dump_json(by_alias=True)
    rehydrated = DiscoverResult.model_validate_json(saved)
    assert rehydrated == discovered

    # ── second connection: zero-RTT — mode=<pin> + prior_discover= sends nothing on entry.
    # A Client cannot be re-entered after exit; build a fresh one via connect(). Without
    # prior_discover= a bare pin would synthesize a blank server_info — passing the cached
    # result is what makes the era-neutral accessors useful on reconnect.
    with anyio.fail_after(5):
        async with connect(mode=LATEST_MODERN_VERSION, prior_discover=rehydrated) as second:
            assert second.protocol_version == LATEST_MODERN_VERSION
            assert second.server_info.name == "reconnect-example"
            assert second.server_capabilities.tools is not None
            assert second.session.discover_result == rehydrated

            result = await second.call_tool("add", {"a": 1, "b": 1})
            assert result.structured_content == {"result": 2}, result


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), needs_connect=True, **client_kw)
