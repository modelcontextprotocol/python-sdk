"""Regression tests for auth context in StreamableHTTP servers."""

import time
from collections.abc import Generator

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import AccessToken
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from tests.test_helpers import run_uvicorn_in_thread


class _EchoTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id=token, scopes=[], expires_at=int(time.time()) + 3600)


async def _handle_whoami(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    access = get_access_token()
    text = access.token if access else "<none>"
    return CallToolResult(content=[TextContent(type="text", text=text)])


async def _handle_list_tools(
    ctx: ServerRequestContext,
    params: PaginatedRequestParams | None,
) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="whoami", input_schema={"type": "object", "properties": {}})])


class _MutableBearerAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self.token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


@pytest.fixture
def stateful_auth_server() -> Generator[str, None, None]:
    server = Server(
        "auth-test-server",
        on_call_tool=_handle_whoami,
        on_list_tools=_handle_list_tools,
    )
    session_manager = StreamableHTTPSessionManager(app=server, stateless=False)
    app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(_EchoTokenVerifier())),
            Middleware(AuthContextMiddleware),
        ],
        lifespan=lambda app: session_manager.run(),
    )

    with run_uvicorn_in_thread(app, host="127.0.0.1", log_level="error") as base_url:
        yield f"{base_url}/mcp"


@pytest.mark.anyio
async def test_get_access_token_reflects_current_request_in_stateful_session(stateful_auth_server: str) -> None:
    auth = _MutableBearerAuth("token-A")
    async with httpx.AsyncClient(
        auth=auth,
        timeout=httpx.Timeout(30, read=30),
        follow_redirects=True,
    ) as http_client:
        async with streamable_http_client(stateful_auth_server, http_client=http_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                first_response = await session.call_tool("whoami", {})
                assert len(first_response.content) == 1
                assert isinstance(first_response.content[0], TextContent)
                assert first_response.content[0].text == "token-A"

                auth.token = "token-B"

                second_response = await session.call_tool("whoami", {})
                assert len(second_response.content) == 1
                assert isinstance(second_response.content[0], TextContent)
                assert second_response.content[0].text == "token-B"
