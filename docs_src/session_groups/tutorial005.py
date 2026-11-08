import asyncio
from collections.abc import Generator

import httpx2

from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters


class BearerAuth(httpx2.Auth):
    """Attach one static bearer token.

    A real OAuth flow uses `OAuthClientProvider` in this same `auth=` slot.
    """

    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


library = StreamableHttpParameters(
    url="http://127.0.0.1:8000/mcp",
    headers={"X-Trace-Id": "library"},
    auth=BearerAuth("library-token"),
)


async def main() -> None:
    async with ClientSessionGroup() as group:
        await group.connect_to_server(library)


if __name__ == "__main__":
    asyncio.run(main())
