"""Regression tests for issue #1250 - refreshed access tokens stay invisible to tools.

A client that refreshes its access token mid-session sends the new token on
the next request's `Authorization` header, but a tool calling
`get_access_token()` kept receiving the token the session was opened with:
the auth context middleware sets the contextvar on each HTTP request's task,
while handlers run in the session's long-lived task.

These tests drive the server over raw HTTP in process because the property
under test - which credential a *changed* `Authorization` header maps to
inside an already-open session - cannot be produced by the typed client API,
whose auth layer owns the header. Everything else (the session manager, the
middleware stack, the tool handler) is the real stack.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool

pytestmark = pytest.mark.anyio

PROTOCOL_VERSION = "2025-06-18"
BASE_URL = "http://127.0.0.1:8000"


class AcceptAllTokenVerifier(TokenVerifier):
    """Verifies any bearer token as the same client; the token string is its identity.

    Models a refresh faithfully: the refreshed token belongs to the same
    client (and principal) as the one it replaces, only the token value differs.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id="test-client", scopes=["mcp"])


def build_app(server: Server) -> tuple[Starlette, StreamableHTTPSessionManager]:
    session_manager = StreamableHTTPSessionManager(app=server, stateless=False, json_response=False)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(AcceptAllTokenVerifier())),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lifespan,
    )
    return app, session_manager


def make_server(call_tool: Any) -> Server:
    server = Server("token-echo")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo_token",
                description="Return the token get_access_token() sees",
                inputSchema={"type": "object"},
            )
        ]

    server.call_tool()(call_tool)
    return server


async def post_message(
    http: httpx.AsyncClient,
    payload: dict[str, Any],
    *,
    token: str,
    session_id: str | None = None,
) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id is not None:
        headers["mcp-session-id"] = session_id
        headers["mcp-protocol-version"] = PROTOCOL_VERSION
    return await http.post("/mcp/", headers=headers, json=payload)


def response_for(response: httpx.Response, request_id: int) -> dict[str, Any]:
    """Extract the JSON-RPC response for `request_id` from an SSE response body."""
    for line in response.text.splitlines():
        if line.startswith("data:"):
            message = json.loads(line.removeprefix("data:").strip())
            if message.get("id") == request_id:
                return message
    raise AssertionError(f"no response for request {request_id} in body: {response.text!r}")


async def open_session(http: httpx.AsyncClient, token: str) -> str:
    """Run the initialize handshake with `token` and return the session id."""
    response = await post_message(
        http,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "issue-1250-regression", "version": "0"},
            },
        },
        token=token,
    )
    assert response.status_code == 200
    session_id = response.headers["mcp-session-id"]
    initialized = await post_message(
        http,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        token=token,
        session_id=session_id,
    )
    assert initialized.status_code == 202
    return session_id


async def call_echo_token(http: httpx.AsyncClient, session_id: str, token: str, request_id: int) -> str:
    """Call the echo tool presenting `token`; return the token the tool observed."""
    response = await post_message(
        http,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "echo_token", "arguments": {}},
        },
        token=token,
        session_id=session_id,
    )
    assert response.status_code == 200
    message = response_for(response, request_id)
    content = message["result"]["content"]
    assert content[0]["type"] == "text"
    return content[0]["text"]


async def test_a_refreshed_token_is_what_tools_see_in_the_same_session() -> None:
    """After a refresh, the next call in the same session observes the new token.

    Steps:
      1. Open a session presenting `token-a`; the tool sees `token-a`.
      2. Present the refreshed `token-b` on the next call in the same session;
         the tool must see `token-b`, not the session-opening `token-a`.
    """

    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        assert name == "echo_token"
        token = get_access_token()
        return [TextContent(type="text", text=token.token if token else "no-token")]

    server = make_server(call_tool)
    app, session_manager = build_app(server)

    with anyio.fail_after(5):
        async with session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                session_id = await open_session(http, "token-a")
                assert await call_echo_token(http, session_id, "token-a", 2) == "token-a"
                assert await call_echo_token(http, session_id, "token-b", 3) == "token-b"


async def test_parallel_sessions_each_see_their_own_current_token() -> None:
    """Interleaved calls in two sessions never observe each other's tokens.

    Both calls are held in flight at the same time (the handler parks on a
    barrier until both have read their token), so the scheduler cannot
    serialize them into looking correct.
    """
    in_flight = 0
    both_in_flight = anyio.Event()
    release = anyio.Event()

    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        nonlocal in_flight
        assert name == "echo_token"
        token = get_access_token()
        seen = token.token if token else "no-token"
        in_flight += 1
        if in_flight == 2:
            both_in_flight.set()
        await release.wait()
        return [TextContent(type="text", text=seen)]

    server = make_server(call_tool)
    app, session_manager = build_app(server)

    results: dict[str, str] = {}

    async def call(http: httpx.AsyncClient, session_id: str, token: str, request_id: int) -> None:
        results[token] = await call_echo_token(http, session_id, token, request_id)

    with anyio.fail_after(5):
        async with session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                session_one = await open_session(http, "token-a")
                session_two = await open_session(http, "token-c")
                async with anyio.create_task_group() as tg:
                    # Session one presents its refreshed token; session two its own.
                    tg.start_soon(call, http, session_one, "token-b", 2)
                    tg.start_soon(call, http, session_two, "token-c", 3)
                    await both_in_flight.wait()
                    release.set()
    assert results == {"token-b": "token-b", "token-c": "token-c"}
