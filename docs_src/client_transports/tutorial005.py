import contextvars

import httpx2

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

auth_token: contextvars.ContextVar[str | None] = contextvars.ContextVar("auth_token", default=None)
trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


async def inject_request_headers(request: httpx2.Request) -> None:
    token = auth_token.get()
    if token is not None:
        request.headers["Authorization"] = f"Bearer {token}"
    current_trace = trace_id.get()
    if current_trace is not None:
        request.headers["X-Trace-ID"] = current_trace


async def main() -> None:
    async with httpx2.AsyncClient(
        event_hooks={"request": [inject_request_headers]},
        timeout=httpx2.Timeout(30.0, read=300.0),
        follow_redirects=True,
    ) as http_client:
        transport = streamable_http_client("http://localhost:8000/mcp", http_client=http_client)
        async with Client(transport) as client:
            auth_token.set("user-123-token")
            trace_id.set("trace-abc")
            first = await client.call_tool("search_books", {"query": "dune"})
            print(first.structured_content)

            auth_token.set("user-456-token")
            trace_id.set("trace-def")
            second = await client.call_tool("search_books", {"query": "neuromancer"})
            print(second.structured_content)
