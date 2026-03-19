"""End-to-end tests for multi-tenant isolation.

These tests exercise the full tenant isolation stack using the in-memory
transport and the high-level ``Client`` class.  They verify that:

1. Tools, resources, and prompts registered under one tenant are invisible
   to other tenants and to the global (None) scope.
2. ``Context.tenant_id`` is correctly populated inside tool handlers.
3. Backward compatibility is preserved — everything works without tenant_id.
"""

from __future__ import annotations

import anyio
import pytest

from mcp import Client
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.prompts.base import Prompt
from mcp.server.mcpserver.resources.types import FunctionResource
from mcp.shared._context import tenant_id_var
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import TextContent

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_multi_tenant_server() -> MCPServer:
    """Build an MCPServer with tenant-scoped tools, resources, and prompts."""
    server = MCPServer("multi-tenant-test")

    # Tenant-A tools / resources / prompts
    def tool_a(x: int) -> str:
        return f"tenant-a:{x}"

    server.add_tool(tool_a, name="compute", tenant_id="tenant-a")
    server.add_resource(
        FunctionResource(uri="data://info", name="info-a", fn=lambda: "secret-a"),
        tenant_id="tenant-a",
    )

    async def prompt_a() -> str:
        return "Hello from tenant-a"

    server.add_prompt(Prompt.from_function(prompt_a, name="greet"), tenant_id="tenant-a")

    # Tenant-B tools / resources / prompts (same names, different data)
    def tool_b(x: int) -> str:
        return f"tenant-b:{x}"

    server.add_tool(tool_b, name="compute", tenant_id="tenant-b")
    server.add_resource(
        FunctionResource(uri="data://info", name="info-b", fn=lambda: "secret-b"),
        tenant_id="tenant-b",
    )

    async def prompt_b() -> str:
        return "Hello from tenant-b"

    server.add_prompt(Prompt.from_function(prompt_b, name="greet"), tenant_id="tenant-b")

    return server


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_tenant_a_sees_only_own_tools():
    """Tenant-A's client lists only tenant-A's tools."""
    server = _build_multi_tenant_server()
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                token = tenant_id_var.set("tenant-a")
                try:
                    await actual.run(
                        server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                    )
                finally:
                    tenant_id_var.reset(token)

            tg.start_soon(run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 1
                assert tools.tools[0].name == "compute"

            tg.cancel_scope.cancel()


async def test_tenant_b_sees_only_own_tools():
    """Tenant-B's client lists only tenant-B's tools."""
    server = _build_multi_tenant_server()
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                token = tenant_id_var.set("tenant-b")
                try:
                    await actual.run(
                        server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                    )
                finally:
                    tenant_id_var.reset(token)

            tg.start_soon(run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 1
                assert tools.tools[0].name == "compute"

            tg.cancel_scope.cancel()


async def test_global_scope_sees_nothing_when_all_tenant_scoped():
    """With no tenant context, no tools/resources/prompts are visible."""
    server = _build_multi_tenant_server()
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: actual.run(
                    server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                )
            )

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 0

                resources = await session.list_resources()
                assert len(resources.resources) == 0

                prompts = await session.list_prompts()
                assert len(prompts.prompts) == 0

            tg.cancel_scope.cancel()


async def test_tenant_tool_returns_correct_result():
    """Calling a tenant-scoped tool returns the correct tenant's result."""
    server = _build_multi_tenant_server()
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                token = tenant_id_var.set("tenant-a")
                try:
                    await actual.run(
                        server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                    )
                finally:
                    tenant_id_var.reset(token)

            tg.start_soon(run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result = await session.call_tool("compute", {"x": 42})
                texts = [c.text for c in result.content if isinstance(c, TextContent)]
                assert any("tenant-a:42" in t for t in texts)

            tg.cancel_scope.cancel()


async def test_tenant_resource_isolation():
    """Tenant-A can read its resource; tenant-B reads a different value."""
    server = _build_multi_tenant_server()
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    for tenant, expected_name in [("tenant-a", "info-a"), ("tenant-b", "info-b")]:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            async with anyio.create_task_group() as tg:

                async def run_server(tid: str = tenant) -> None:
                    token = tenant_id_var.set(tid)
                    try:
                        await actual.run(
                            server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                        )
                    finally:
                        tenant_id_var.reset(token)

                tg.start_soon(run_server)

                async with ClientSession(client_read, client_write) as session:
                    await session.initialize()
                    resources = await session.list_resources()
                    assert len(resources.resources) == 1
                    assert resources.resources[0].name == expected_name

                tg.cancel_scope.cancel()


async def test_tenant_prompt_isolation():
    """Each tenant sees only its own prompts."""
    server = _build_multi_tenant_server()
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    for tenant in ["tenant-a", "tenant-b"]:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            async with anyio.create_task_group() as tg:

                async def run_server(tid: str = tenant) -> None:
                    token = tenant_id_var.set(tid)
                    try:
                        await actual.run(
                            server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                        )
                    finally:
                        tenant_id_var.reset(token)

                tg.start_soon(run_server)

                async with ClientSession(client_read, client_write) as session:
                    await session.initialize()
                    prompts = await session.list_prompts()
                    assert len(prompts.prompts) == 1
                    assert prompts.prompts[0].name == "greet"

                    result = await session.get_prompt("greet")
                    text = result.messages[0].content.text  # type: ignore[union-attr]
                    assert tenant in text

                tg.cancel_scope.cancel()


async def test_context_tenant_id_available_in_tool():
    """The ``Context.tenant_id`` property is populated inside a tool handler."""
    captured_tenant: list[str | None] = []

    server = MCPServer("ctx-test")

    def check_tenant(ctx: Context) -> str:
        captured_tenant.append(ctx.tenant_id)
        return "ok"

    # Register under the tenant scope that will be active during the test
    server.add_tool(check_tenant, name="check_tenant", tenant_id="my-tenant")
    actual = server._lowlevel_server  # type: ignore[reportPrivateUsage]

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                token = tenant_id_var.set("my-tenant")
                try:
                    await actual.run(
                        server_read, server_write, actual.create_initialization_options(), raise_exceptions=True
                    )
                finally:
                    tenant_id_var.reset(token)

            tg.start_soon(run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                await session.call_tool("check_tenant", {})

            tg.cancel_scope.cancel()

    assert captured_tenant == ["my-tenant"]


async def test_backward_compat_no_tenant():
    """Without tenant_id set, tools/resources/prompts in global scope work normally."""
    server = MCPServer("compat-test")

    @server.tool()
    def hello(name: str) -> str:
        return f"Hi {name}"

    @server.resource("test://data")
    def data() -> str:
        return "some data"

    @server.prompt()
    def ask() -> str:
        return "Please answer"

    async with Client(server) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 1

        result = await client.call_tool("hello", {"name": "World"})
        assert any("Hi World" in c.text for c in result.content if isinstance(c, TextContent))

        resources = await client.list_resources()
        assert len(resources.resources) == 1

        prompts = await client.list_prompts()
        assert len(prompts.prompts) == 1
