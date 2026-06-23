"""Call the bearer-gated server with a static ``Authorization`` header; assert the principal."""

import sys
import traceback
from typing import Any

import anyio
import httpx

from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.version import LATEST_MODERN_VERSION
from stories._harness import argv_after

from .server import DEMO_TOKEN, REQUIRED_SCOPE

# ``Client(url)`` has no ``auth=`` / ``http_client=`` passthrough yet, so the bearer
# header is threaded at the ``httpx.AsyncClient`` layer. The harness reads this
# module-level dict and splats it into the in-process bridge client.
http_client_kw: dict[str, Any] = {"headers": {"authorization": f"Bearer {DEMO_TOKEN}"}}


async def scenario(client: Client) -> None:
    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["whoami"]

    result = await client.call_tool("whoami", {})
    assert not result.is_error, result
    assert result.structured_content == {
        "subject": "demo-user",
        "client_id": "demo-client",
        "scopes": [REQUIRED_SCOPE],
    }, result.structured_content


if __name__ == "__main__":
    # HTTP-only auth story; --http takes the MCP endpoint URL. Hand-rolled because
    # ``connect_from_args`` cannot thread the bearer header; this IS the recipe.
    url = argv_after("--http", default="http://127.0.0.1:8000/mcp")
    mode = "legacy" if "--legacy" in sys.argv else LATEST_MODERN_VERSION

    async def _main() -> None:
        with anyio.fail_after(30):
            async with (
                httpx.AsyncClient(**http_client_kw) as http_client,
                Client(streamable_http_client(url, http_client=http_client), mode=mode) as client,
            ):
                await scenario(client)

    try:
        anyio.run(_main)
    except Exception:
        print("FAIL: bearer_auth (http)", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1) from None
    print("OK: bearer_auth (http)", file=sys.stderr)
    raise SystemExit(0)
