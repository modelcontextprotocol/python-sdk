"""Minimal bearer-token authentication example.

Demonstrates the simplest possible MCP client authentication: a bearer token
from an environment variable. `BearerAuth` is an `httpx.Auth` implementation
that calls `token()` before every request and optionally `on_unauthorized()`
on 401 before retrying once.

For full OAuth flows (authorization code, PKCE, dynamic client registration),
see `oauth_client.py` and use `OAuthClientProvider` instead — both plug into
the same `auth` parameter.

Run against any MCP server that accepts bearer tokens:

    MCP_TOKEN=your-token MCP_SERVER_URL=http://localhost:8001/mcp uv run bearer-auth-client
"""

import asyncio
import os

from mcp.client import Client
from mcp.client.auth import BearerAuth


async def main() -> None:
    server_url = os.environ.get("MCP_SERVER_URL", "http://localhost:8001/mcp")
    token = os.environ.get("MCP_TOKEN")

    if not token:
        raise SystemExit("Set MCP_TOKEN to your bearer token")

    # token() is called before every request. With no on_unauthorized handler,
    # a 401 raises UnauthorizedError immediately — no retry.
    auth = BearerAuth(token)

    async with Client(server_url, auth=auth) as client:
        tools = await client.list_tools()
        print(f"Available tools: {[t.name for t in tools.tools]}")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
