import time

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import AccessToken
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)


class _EchoTokenVerifier:
    """Accepts any bearer token and echoes it back as the verified AccessToken."""

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id=token, scopes=[], expires_at=int(time.time()) + 3600)


async def _handle_whoami(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    access = get_access_token()
    text = access.token if access else "<none>"
    return CallToolResult(content=[TextContent(type="text", text=text)])


async def _handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="whoami", input_schema={"type": "object", "properties": {}})])


class _MutableBearerAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


@pytest.mark.anyio
async def test_get_access_token_reflects_current_request_in_stateful_session() -> None:
    host = "testserver"

    server = Server(
        "auth-test-server",
        on_call_tool=_handle_whoami,
        on_list_tools=_handle_list_tools,
    )

    security = TransportSecuritySettings(
        allowed_hosts=[host, f"{host}:*"],
        allowed_origins=[f"http://{host}:*"],
    )
    session_manager = StreamableHTTPSessionManager(app=server, security_settings=security, stateless=False)

    asgi_app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(_EchoTokenVerifier())),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lambda app: session_manager.run(),
    )

    auth = _MutableBearerAuth("token-A")
    async with asgi_app.router.lifespan_context(asgi_app):
        async with (
            httpx.ASGITransport(asgi_app) as transport,
            httpx.AsyncClient(
                transport=transport,
                base_url=f"http://{host}",
                auth=auth,
                timeout=httpx.Timeout(30, read=30),
                follow_redirects=True,
            ) as http_client,
        ):
            transport_ctx = streamable_http_client(f"http://{host}/mcp", http_client=http_client)
            async with Client(transport_ctx) as client:
                r1 = await client.call_tool("whoami", {})
                assert isinstance(r1.content[0], TextContent)
                assert r1.content[0].text == "token-A"

                auth.token = "token-B"
                r2 = await client.call_tool("whoami", {})
                assert isinstance(r2.content[0], TextContent)
                assert r2.content[0].text == "token-B"
