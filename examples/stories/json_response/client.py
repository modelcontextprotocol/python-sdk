"""Regular ``Client`` against a JSON-only server; assert mid-call progress is dropped.

``RAW_ENVELOPE_BODY`` / ``MODERN_HEADERS`` are the exact wire shape a 2026-era client
sends — this is the only story that shows it. ``main`` posts that body by hand and
asserts the response is a single ``application/json`` body with no session id.
"""

import httpx

from mcp.client import Client
from mcp.shared.version import LATEST_MODERN_VERSION
from mcp.types import TextContent
from stories._harness import Target, run_client

# The raw 2026-07-28 POST envelope: per-request `_meta` replaces the initialize handshake.
# The key/header strings are spelled out on purpose — this is the raw-wire story. In code
# use the named constants instead: `mcp.types.PROTOCOL_VERSION_META_KEY` /
# `CLIENT_INFO_META_KEY` / `CLIENT_CAPABILITIES_META_KEY` and
# `mcp.shared.inbound.MCP_PROTOCOL_VERSION_HEADER` (`legacy_routing/` shows that form).
RAW_ENVELOPE_BODY: dict[str, object] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": LATEST_MODERN_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "raw-probe", "version": "0.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    },
}
MODERN_HEADERS: dict[str, str] = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": LATEST_MODERN_VERSION,
    "mcp-method": "tools/list",
}


async def main(target: Target, *, mode: str = "auto", http: httpx.AsyncClient) -> None:
    async with Client(target, mode=mode) as client:
        assert client.protocol_version == LATEST_MODERN_VERSION

        progress_seen: list[float] = []

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            progress_seen.append(progress)

        result = await client.call_tool("greet", {"name": "json"}, progress_callback=on_progress)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello, json!"
        assert result.structured_content == {"result": "Hello, json!"}, result

        # The tool called report_progress(0.5) but the modern HTTP JSON path has no
        # back-channel for mid-call notifications, so the callback is never invoked.
        assert progress_seen == [], f"expected progress to be dropped, got {progress_seen}"

        # Hand-craft a 2026 POST and assert it comes back as a single JSON body, no session.
        response = await http.post("/mcp", json=RAW_ENVELOPE_BODY, headers=MODERN_HEADERS)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].split(";", 1)[0] == "application/json"
        assert "mcp-session-id" not in response.headers
        payload = response.json()
        assert payload["id"] == 1
        assert [t["name"] for t in payload["result"]["tools"]] == ["greet"]


if __name__ == "__main__":
    run_client(main)
