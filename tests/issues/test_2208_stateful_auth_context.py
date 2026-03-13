"""Regression test for issue #2208.

In stateful streamable HTTP sessions, get_access_token() must reflect the
Authorization header from the current request, not the one that created the
session's background receive task.
"""

import time

import httpx
import pytest
from pydantic import AnyHttpUrl

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool


class EchoTokenVerifier:
    """Accept any bearer token and expose it in the authenticated user."""

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id=token, scopes=[], expires_at=int(time.time()) + 3600)


class MutableBearerAuth(httpx.Auth):
    """Update the bearer token between requests without rebuilding the client."""

    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


async def handle_whoami(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    access_token = get_access_token()
    token = access_token.token if access_token else "<none>"
    return CallToolResult(content=[TextContent(type="text", text=token)])


async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="whoami",
                input_schema={"type": "object", "properties": {}},
            )
        ]
    )


@pytest.mark.anyio
async def test_get_access_token_uses_current_request_in_stateful_streamable_http_session() -> None:
    server = Server(
        "auth-test-server",
        on_call_tool=handle_whoami,
        on_list_tools=handle_list_tools,
    )
    app = server.streamable_http_app(
        host="testserver",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl("https://testserver/mcp"),
        ),
        token_verifier=EchoTokenVerifier(),
    )
    auth = MutableBearerAuth("token-A")

    async with (
        app.router.lifespan_context(app),
        httpx.ASGITransport(app) as transport,
        httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            auth=auth,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=30.0),
        ) as http_client,
        streamable_http_client("http://testserver/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        first_response = await session.call_tool("whoami", {})
        assert isinstance(first_response.content[0], TextContent)
        assert first_response.content[0].text == "token-A"

        auth.token = "token-B"

        second_response = await session.call_tool("whoami", {})
        assert isinstance(second_response.content[0], TextContent)
        assert second_response.content[0].text == "token-B"
