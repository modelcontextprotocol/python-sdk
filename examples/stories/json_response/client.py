"""Regular ``Client`` against a JSON-only server; assert mid-call progress is dropped.

``RAW_ENVELOPE_BODY`` / ``MODERN_HEADERS`` are the exact wire shape a 2026-era client
sends — this is the only story that shows it. ``scenario`` posts that body by hand
and asserts the response is a single ``application/json`` body with no session id.
"""

import sys
import traceback

import anyio
import httpx

from mcp.client import Client
from mcp.shared.version import LATEST_MODERN_VERSION
from mcp.types import TextContent
from stories._harness import argv_after

# The raw 2026-07-28 POST envelope: per-request `_meta` replaces the initialize handshake.
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


async def scenario(client: Client, http: httpx.AsyncClient) -> None:
    assert client.protocol_version == LATEST_MODERN_VERSION

    progress_seen: list[float] = []

    async def _on_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_seen.append(progress)

    result = await client.call_tool("greet", {"name": "json"}, progress_callback=_on_progress)
    assert isinstance(result.content[0], TextContent) and result.content[0].text == "Hello, json!"
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
    # HTTP-only story; --http takes the server origin (without /mcp).
    # Hand-rolled because `run_client` has no needs_http arm; matches its
    # fail_after(30) + FAIL/OK + exit-code semantics inline.
    origin = argv_after("--http")

    async def _main() -> None:
        with anyio.fail_after(30):
            async with (
                httpx.AsyncClient(base_url=origin) as http_client,
                Client(f"{origin}/mcp", mode=LATEST_MODERN_VERSION) as client,
            ):
                await scenario(client, http_client)

    try:
        anyio.run(_main)
    except Exception:
        print("FAIL: json_response (http/modern)", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1) from None
    print("OK: json_response (http/modern)", file=sys.stderr)
    raise SystemExit(0)
