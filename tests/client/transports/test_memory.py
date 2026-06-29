from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import anyio.lowlevel
import mcp_types as types
import pytest
from mcp_types import ListResourcesResult, Resource

from mcp import Client
from mcp.client import _memory
from mcp.client._memory import InMemoryTransport
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer


@pytest.fixture
def simple_server() -> Server:
    async def handle_list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:  # pragma: no cover
        return ListResourcesResult(
            resources=[
                Resource(
                    uri="memory://test",
                    name="Test Resource",
                    description="A test resource",
                )
            ]
        )

    return Server(name="test_server", on_list_resources=handle_list_resources)


@pytest.fixture
def mcpserver_server() -> MCPServer:
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"Hello, {name}!"

    @server.resource("test://resource")
    def test_resource() -> str:  # pragma: no cover
        """A test resource."""
        return "Test content"

    return server


pytestmark = pytest.mark.anyio


async def test_with_server(simple_server: Server):
    transport = InMemoryTransport(simple_server)
    async with transport as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None


async def test_with_mcpserver(mcpserver_server: MCPServer):
    transport = InMemoryTransport(mcpserver_server)
    async with transport as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None


async def test_server_is_running(mcpserver_server: MCPServer):
    async with Client(mcpserver_server, mode="legacy") as client:
        assert client.server_capabilities.tools is not None


async def test_list_tools(mcpserver_server: MCPServer):
    async with Client(mcpserver_server, mode="legacy") as client:
        tools_result = await client.list_tools()
        assert len(tools_result.tools) > 0
        tool_names = [t.name for t in tools_result.tools]
        assert "greet" in tool_names


async def test_call_tool(mcpserver_server: MCPServer):
    async with Client(mcpserver_server, mode="legacy") as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result is not None
        assert len(result.content) > 0
        assert "Hello, World!" in str(result.content[0])


async def test_raise_exceptions(mcpserver_server: MCPServer):
    transport = InMemoryTransport(mcpserver_server, raise_exceptions=True)
    async with transport as (read_stream, _write_stream):
        assert read_stream is not None


async def test_aexit_with_well_behaved_lifespan_runs_teardown_without_cancel():
    """The transport closes the streams and waits for a natural server exit, so teardown sees no cancellation."""
    teardown_ran = anyio.Event()

    @asynccontextmanager
    async def lifespan(_: Server[Any]) -> AsyncIterator[dict[str, Any]]:
        yield {}
        await anyio.lowlevel.checkpoint()
        teardown_ran.set()

    server = Server(name="test_server", lifespan=lifespan)
    with anyio.fail_after(5):
        async with InMemoryTransport(server):
            pass
    assert teardown_ran.is_set()


async def test_aexit_with_blocking_lifespan_is_bounded(monkeypatch: pytest.MonkeyPatch):
    """After EOF the transport waits `SERVER_SHUTDOWN_GRACE` for a natural exit, then cancels as a backstop."""
    monkeypatch.setattr(_memory, "SERVER_SHUTDOWN_GRACE", 0.05)
    teardown_started = anyio.Event()

    @asynccontextmanager
    async def blocking_lifespan(_: Server[Any]) -> AsyncIterator[dict[str, Any]]:
        yield {}
        teardown_started.set()
        await anyio.Event().wait()

    server = Server(name="test_server", lifespan=blocking_lifespan)
    with anyio.fail_after(5):
        async with InMemoryTransport(server):
            pass
    assert teardown_started.is_set()
