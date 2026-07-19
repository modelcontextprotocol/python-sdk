"""Call the bearer-gated server through an already-authed (``build_auth``, HTTP-only) transport; assert ``whoami``."""

from collections.abc import Generator

import httpx2

from mcp.client import Client
from stories._harness import Target, run_client

from .server import DEMO_TOKEN, REQUIRED_SCOPE


class StaticBearerAuth(httpx2.Auth):
    """``httpx2.Auth`` that attaches a fixed ``Authorization: Bearer <token>`` to every request."""

    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


def build_auth(_http: httpx2.AsyncClient) -> httpx2.Auth:
    """The demo bearer token as an ``httpx2.Auth``.

    ``Client(url, auth=...)`` doesn't exist yet, so the harness threads this onto the underlying
    ``httpx2.AsyncClient`` and the target ``main`` receives is already routed through it.
    """
    return StaticBearerAuth(DEMO_TOKEN)


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
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
    run_client(main)
