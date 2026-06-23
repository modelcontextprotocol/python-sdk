"""Connect at both eras to one app; assert the built-in router and the predicate agree."""

from typing import Any

from mcp import types
from mcp.client import Client
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER, InboundLadderRejection
from mcp.shared.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from mcp.types import CLIENT_CAPABILITIES_META_KEY, CLIENT_INFO_META_KEY, PROTOCOL_VERSION_META_KEY
from stories._harness import Connect, connect_from_args, run_client

from .server import classify_era


def _arm(result: types.CallToolResult) -> str:
    first = result.content[0]
    assert isinstance(first, types.TextContent)
    return first.text


async def scenario(client: Client, connect: Connect) -> None:
    # ── modern leg: harness-supplied client at mode="auto" probed server/discover.
    assert client.protocol_version == LATEST_MODERN_VERSION
    assert _arm(await client.call_tool("which_arm", {})) == "modern"

    # ── legacy leg: same /mcp endpoint, initialize handshake → sessionful 2025 path.
    async with connect(mode="legacy") as legacy:
        assert legacy.protocol_version == LATEST_HANDSHAKE_VERSION
        assert _arm(await legacy.call_tool("which_arm", {})) == "legacy"

    # ── the exported predicate, shown directly. A body carrying the 2026 _meta
    # envelope classifies as modern; a bare initialize body classifies as legacy;
    # a 2026 envelope whose header disagrees is a rejection (NOT legacy).
    modern_body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
                CLIENT_INFO_META_KEY: {"name": "demo", "version": "0"},
                CLIENT_CAPABILITIES_META_KEY: {},
            }
        },
    }
    assert classify_era(modern_body, headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION}) == "modern"

    legacy_body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert classify_era(legacy_body, headers={}) == "legacy"

    mismatched = classify_era(modern_body, headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_HANDSHAKE_VERSION})
    assert isinstance(mismatched, InboundLadderRejection), mismatched


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), needs_connect=True, mode="auto")
