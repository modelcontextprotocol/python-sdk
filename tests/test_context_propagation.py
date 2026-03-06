import contextvars
import multiprocessing
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

import httpx
import pytest
import uvicorn
from inline_snapshot import snapshot
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

import mcp.types as types
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from tests.test_helpers import wait_for_server

TEST_CONTEXTVAR = contextvars.ContextVar("test_var", default="initial")


@contextmanager
def set_test_contextvar(value: str) -> Iterator[None]:
    token = TEST_CONTEXTVAR.set(value)
    try:
        yield
    finally:
        TEST_CONTEXTVAR.reset(token)


# Sends header CLIENT_HEADER with a configured value
class SendClientHeaderTransport(httpx.AsyncHTTPTransport):
    def __init__(self) -> None:
        super().__init__()
        self.client_header_value: str = "initial"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.headers["CLIENT_HEADER"] = self.client_header_value
        return await super().handle_async_request(request)


# Intercepts the httpx call to capture the contextvar's value
class ContextCapturingTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__()
        self.captured_context_var: str | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_context_var = TEST_CONTEXTVAR.get()
        return await super().handle_async_request(request)


def create_server() -> MCPServer:
    mcp = MCPServer("test_server")

    # tool that returns the value of TEST_CONTEXT_VAR.
    @mcp.tool()
    async def my_tool() -> str:
        return TEST_CONTEXTVAR.get()

    return mcp


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(transport: Literal["sse", "streamable_http"], port: int):  # pragma: no cover
    class ContextVarMiddleware(BaseHTTPMiddleware):  # pragma: lax no cover
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            actual_value = request.headers.get("CLIENT_HEADER")
            with set_test_contextvar(f"from middleware CLIENT_HEADER={actual_value}"):
                return await call_next(request)

    server = create_server()

    match transport:
        case "sse":
            app = server.sse_app(host="127.0.0.1")
        case "streamable_http":
            app = server.streamable_http_app(host="127.0.0.1")

    app.add_middleware(ContextVarMiddleware)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


@contextmanager
def start_server_process(transport: Literal["sse", "streamable_http"], port: int):
    """Start server in a separate process."""
    process = multiprocessing.Process(target=run_server, args=(transport, port))

    process.start()
    try:
        wait_for_server(port)
        yield process
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_memory_transport_client_to_server():
    async with Client(create_server()) as client:
        with set_test_contextvar("client_value"):
            result = await client.call_tool(name="my_tool")

            assert isinstance(result, types.CallToolResult)
            assert result.content == snapshot([types.TextContent(text="client_value")])


@pytest.mark.anyio
async def test_streamable_http_asgi_to_mcpserver(server_port: int):
    with start_server_process("streamable_http", server_port):
        async with (
            SendClientHeaderTransport() as transport,
            httpx.AsyncClient(transport=transport) as http_client,
            Client(streamable_http_client(f"http://127.0.0.1:{server_port}/mcp", http_client=http_client)) as client,
        ):
            transport.client_header_value = "expected_value"
            result = await client.call_tool("my_tool")
            assert result.content == snapshot([types.TextContent(text="from middleware CLIENT_HEADER=expected_value")])


@pytest.mark.anyio
async def test_streamable_http_mcpclient_to_httpx(server_port: int):
    with start_server_process("streamable_http", server_port):
        async with (
            ContextCapturingTransport() as transport,
            httpx.AsyncClient(transport=transport) as http_client,
            Client(streamable_http_client(f"http://127.0.0.1:{server_port}/mcp", http_client=http_client)) as client,
        ):
            with set_test_contextvar("client_value_list"):
                await client.list_tools()
                assert transport.captured_context_var == snapshot("client_value_list")

            with set_test_contextvar("client_value_call_tool"):  # pragma: lax no cover
                await client.call_tool("my_tool")
                assert transport.captured_context_var == snapshot("client_value_call_tool")


@pytest.mark.anyio
async def test_sse_asgi_to_mcpserver(server_port: int):
    transport = SendClientHeaderTransport()

    def client_factory(
        headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None, auth: httpx.Auth | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, headers=headers, timeout=timeout, auth=auth)

    with start_server_process("sse", server_port):
        async with Client(
            sse_client(f"http://127.0.0.1:{server_port}/sse", httpx_client_factory=client_factory)
        ) as client:
            transport.client_header_value = "expected_value"
            result = await client.call_tool("my_tool")
            assert result.content == snapshot([types.TextContent(text="from middleware CLIENT_HEADER=expected_value")])


@pytest.mark.anyio
async def test_sse_mcpclient_to_httpx(server_port: int):
    transport = ContextCapturingTransport()

    def client_factory(
        headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None, auth: httpx.Auth | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, headers=headers, timeout=timeout, auth=auth)

    with start_server_process("sse", server_port):
        async with Client(
            sse_client(f"http://127.0.0.1:{server_port}/sse", httpx_client_factory=client_factory)
        ) as client:
            with set_test_contextvar("client_value_list"):
                await client.list_tools()
                assert transport.captured_context_var == snapshot("client_value_list")

            with set_test_contextvar("client_value_call_tool"):  # pragma: lax no cover
                await client.call_tool("my_tool")
                assert transport.captured_context_var == snapshot("client_value_call_tool")
