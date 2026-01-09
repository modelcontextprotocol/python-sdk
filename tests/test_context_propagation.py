import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from inline_snapshot import snapshot
from starlette.types import Receive, Scope, Send

import mcp.types as types
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

TEST_CONTEXTVAR = contextvars.ContextVar("test_var", default="initial")
HOST = "testserver"


@contextmanager
def set_test_contextvar(value: str) -> Iterator[None]:
    token = TEST_CONTEXTVAR.set(value)
    try:
        yield
    finally:
        TEST_CONTEXTVAR.reset(token)


@pytest.fixture
def server() -> MCPServer:
    mcp = MCPServer("test_server")

    # tool that returns the value of TEST_CONTEXT_VAR.
    @mcp.tool()
    async def my_tool() -> str:
        return TEST_CONTEXTVAR.get()

    return mcp


@pytest.mark.anyio
async def test_memory_transport_client_to_server(server: MCPServer):
    async with Client(server) as client:
        with set_test_contextvar("client_value"):
            result = await client.call_tool(name="my_tool")

            assert isinstance(result, types.CallToolResult)
            assert result.content == snapshot([types.TextContent(text="client_value")])


@pytest.mark.anyio
async def test_streamable_http_asgi_to_mcpserver(server: MCPServer):
    mcp_app = server.streamable_http_app(host=HOST)

    # Wrap it in a middleware that sets the contextvar
    async def middleware_app(scope: Scope, receive: Receive, send: Send):
        with set_test_contextvar("from_middleware"):
            await mcp_app(scope, receive, send)

    async with (
        mcp_app.router.lifespan_context(middleware_app),
        httpx.ASGITransport(app=middleware_app) as transport,
        httpx.AsyncClient(transport=transport) as http_client,
        Client(streamable_http_client(f"http://{HOST}/mcp", http_client=http_client)) as client,
    ):
        result = await client.call_tool("my_tool")
        assert result.content == snapshot([types.TextContent(text="from_middleware")])


@pytest.mark.anyio
async def test_streamable_http_mcpclient_to_httpx(server: MCPServer):
    mcp_app = server.streamable_http_app(host=HOST)

    captured_context_var = None

    # Intercepts the httpx call and capture the contextvar's value
    class ContextCapturingASGITransport(httpx.ASGITransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal captured_context_var
            captured_context_var = TEST_CONTEXTVAR.get()
            return await super().handle_async_request(request)

    async with (
        mcp_app.router.lifespan_context(mcp_app),
        ContextCapturingASGITransport(app=mcp_app) as transport,
        httpx.AsyncClient(transport=transport) as http_client,
        Client(streamable_http_client(f"http://{HOST}/mcp", http_client=http_client)) as client,
    ):
        with set_test_contextvar("client_value_list"):
            await client.list_tools()
            assert captured_context_var == snapshot("client_value_list")

        with set_test_contextvar("client_value_call_tool"):
            await client.call_tool("my_tool")
            assert captured_context_var == snapshot("client_value_call_tool")
