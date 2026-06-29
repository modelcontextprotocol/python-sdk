"""Connect at both eras to one app — so `main` takes `targets` — and assert the built-in router and predicate agree."""

from typing import Any

import mcp_types as types
from mcp_types import CLIENT_CAPABILITIES_META_KEY, CLIENT_INFO_META_KEY, PROTOCOL_VERSION_META_KEY
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from mcp.client import Client
from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_PROTOCOL_VERSION_HEADER, InboundLadderRejection
from stories._harness import TargetFactory, run_client

from .server import classify_era


def _arm(result: types.CallToolResult) -> str:
    first = result.content[0]
    assert isinstance(first, types.TextContent)
    return first.text


async def main(targets: TargetFactory, *, mode: str = "auto") -> None:
    # Modern arm: the default `auto` mode probes `server/discover` → the stateless 2026 path.
    async with Client(targets(), mode=mode) as modern:
        assert modern.protocol_version == LATEST_MODERN_VERSION
        assert _arm(await modern.call_tool("which_arm", {})) == "modern"

    # Legacy arm: the SAME /mcp endpoint, `initialize` handshake → sessionful 2025 path.
    async with Client(targets(), mode="legacy") as legacy:
        assert legacy.protocol_version == LATEST_HANDSHAKE_VERSION
        assert _arm(await legacy.call_tool("which_arm", {})) == "legacy"

    # The exported predicate: a 2026 _meta envelope with matching `Mcp-Protocol-Version`/`Mcp-Method`
    # headers is modern; a bare initialize body is legacy; a header that disagrees is a rejection (NOT legacy).
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
    modern_headers = {MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION, MCP_METHOD_HEADER: "tools/list"}
    assert classify_era(modern_body, headers=modern_headers) == "modern"

    legacy_body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert classify_era(legacy_body, headers={}) == "legacy"

    # The SAME complete header set, with only the protocol version disagreeing with the body.
    mismatched_headers = modern_headers | {MCP_PROTOCOL_VERSION_HEADER: LATEST_HANDSHAKE_VERSION}
    mismatched = classify_era(modern_body, headers=mismatched_headers)
    assert isinstance(mismatched, InboundLadderRejection), mismatched


if __name__ == "__main__":
    run_client(main)
