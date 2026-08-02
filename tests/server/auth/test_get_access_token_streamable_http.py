import time

import anyio
import httpx2
import pytest
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    ProgressNotificationParams,
    TextContent,
    Tool,
)
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


class _EchoTokenVerifier:
    """Accepts any bearer token and echoes it back as the verified AccessToken."""

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id="test-client", scopes=[], expires_at=int(time.time()) + 3600)


async def _handle_whoami(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    access = get_access_token()
    text = access.token if access else "<none>"
    return CallToolResult(content=[TextContent(type="text", text=text)])


async def _handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="whoami", input_schema={"type": "object", "properties": {}})])


class _MutableBearerAuth(httpx2.Auth):
    def __init__(self, token: str | None) -> None:
        self.token = token

    def auth_flow(self, request: httpx2.Request):
        if self.token is not None:
            request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


async def _call_whoami(client: Client) -> str:
    result = await client.call_tool("whoami", {})
    assert isinstance(result.content[0], TextContent)
    return result.content[0].text


@pytest.mark.anyio
async def test_get_access_token_reflects_current_request_in_stateful_session() -> None:
    host = "testserver"

    server = Server(
        "auth-test-server",
        on_call_tool=_handle_whoami,
        on_list_tools=_handle_list_tools,
    )

    session_manager = StreamableHTTPSessionManager(app=server, stateless=False)

    asgi_app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(_EchoTokenVerifier())),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lambda app: session_manager.run(),
    )

    async with asgi_app.router.lifespan_context(asgi_app):
        auth = _MutableBearerAuth("token-A")
        async with (
            httpx2.ASGITransport(asgi_app) as transport,
            httpx2.AsyncClient(
                transport=transport,
                base_url=f"http://{host}",
                auth=auth,
                timeout=httpx2.Timeout(30, read=30),
                follow_redirects=True,
            ) as http_client,
            Client(streamable_http_client(f"http://{host}/mcp", http_client=http_client), mode="legacy") as client,
        ):
            assert await _call_whoami(client) == "token-A"

            auth.token = "token-B"
            assert await _call_whoami(client) == "token-B"


@pytest.mark.anyio
async def test_notification_handler_get_access_token_reflects_current_request_in_stateful_session() -> None:
    host = "testserver"
    send_token, receive_token = anyio.create_memory_object_stream[str](10)

    async def handle_progress(ctx: ServerRequestContext, params: ProgressNotificationParams) -> None:
        access = get_access_token()
        await send_token.send(access.token if access else "<none>")

    server = Server(
        "auth-test-server",
        on_call_tool=_handle_whoami,
        on_list_tools=_handle_list_tools,
    )
    server.add_notification_handler("notifications/progress", ProgressNotificationParams, handle_progress)

    session_manager = StreamableHTTPSessionManager(app=server, stateless=False)

    asgi_app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(_EchoTokenVerifier())),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lambda app: session_manager.run(),
    )

    async with send_token, receive_token, asgi_app.router.lifespan_context(asgi_app):
        auth = _MutableBearerAuth("token-A")
        async with (
            httpx2.ASGITransport(asgi_app) as transport,
            httpx2.AsyncClient(
                transport=transport,
                base_url=f"http://{host}",
                auth=auth,
                timeout=httpx2.Timeout(30, read=30),
                follow_redirects=True,
            ) as http_client,
            Client(streamable_http_client(f"http://{host}/mcp", http_client=http_client), mode="legacy") as client,
        ):
            await client.send_progress_notification("token-A", 0.1)  # pyright: ignore[reportDeprecated]
            with anyio.fail_after(5):
                assert await receive_token.receive() == "token-A"

            auth.token = "token-B"
            await client.send_progress_notification("token-B", 0.2)  # pyright: ignore[reportDeprecated]
            with anyio.fail_after(5):
                assert await receive_token.receive() == "token-B"
