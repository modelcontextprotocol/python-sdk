"""Tests for tenant-scoped MCPServer server integration.

Validates that tenant_id flows from MCPServer public methods down to the
underlying managers, and that Context exposes tenant_id correctly.
"""

import pytest

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.prompts.base import Prompt
from mcp.server.mcpserver.resources.types import FunctionResource

pytestmark = pytest.mark.anyio


# --- Context.tenant_id property ---


def test_context_tenant_id_without_request_context():
    """Context.tenant_id returns None when no request context is set."""
    ctx = Context()
    assert ctx.tenant_id is None


def test_context_tenant_id_with_request_context():
    """Context.tenant_id returns the tenant_id from the request context."""
    from mcp.server.context import ServerRequestContext

    # Create a minimal ServerRequestContext with tenant_id
    # We need real streams for ServerSession but won't use them

    rc = ServerRequestContext(
        session=None,  # type: ignore[arg-type]
        lifespan_context=None,
        experimental={},
        tenant_id="tenant-x",
    )
    ctx = Context(request_context=rc)
    assert ctx.tenant_id == "tenant-x"


def test_context_tenant_id_none_in_request_context():
    """Context.tenant_id returns None when request context has no tenant_id."""
    from mcp.server.context import ServerRequestContext

    rc = ServerRequestContext(
        session=None,  # type: ignore[arg-type]
        lifespan_context=None,
        experimental={},
    )
    ctx = Context(request_context=rc)
    assert ctx.tenant_id is None


# --- MCPServer public methods with tenant_id ---


async def test_list_tools_with_tenant_id():
    """list_tools filters by tenant_id."""
    server = MCPServer("test")

    def tool_a() -> str:  # pragma: no cover
        return "a"

    def tool_b() -> str:  # pragma: no cover
        return "b"

    server.add_tool(tool_a, name="shared", tenant_id="tenant-a")
    server.add_tool(tool_b, name="shared", tenant_id="tenant-b")

    tools_a = await server.list_tools(tenant_id="tenant-a")
    tools_b = await server.list_tools(tenant_id="tenant-b")
    tools_global = await server.list_tools()

    assert len(tools_a) == 1
    assert tools_a[0].name == "shared"
    assert len(tools_b) == 1
    assert tools_b[0].name == "shared"
    assert len(tools_global) == 0


async def test_call_tool_with_tenant_id():
    """call_tool respects tenant scope."""
    server = MCPServer("test")

    def tool_a() -> str:
        return "result-a"

    def tool_b() -> str:
        return "result-b"

    server.add_tool(tool_a, name="do_work", tenant_id="tenant-a")
    server.add_tool(tool_b, name="do_work", tenant_id="tenant-b")

    result_a = await server.call_tool("do_work", {}, tenant_id="tenant-a")
    result_b = await server.call_tool("do_work", {}, tenant_id="tenant-b")

    # Results are non-empty (structured output returns a tuple)
    assert result_a is not None
    assert result_b is not None


async def test_call_tool_wrong_tenant_raises():
    """Calling a tool under the wrong tenant raises an error."""
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer("test")

    def my_tool() -> str:  # pragma: no cover
        return "x"

    server.add_tool(my_tool, tenant_id="tenant-a")

    with pytest.raises(ToolError):
        await server.call_tool("my_tool", {}, tenant_id="tenant-b")


async def test_list_resources_with_tenant_id():
    """list_resources filters by tenant_id."""
    server = MCPServer("test")

    resource_a = FunctionResource(uri="file:///data", name="data-a", fn=lambda: "a")
    resource_b = FunctionResource(uri="file:///data", name="data-b", fn=lambda: "b")

    server.add_resource(resource_a, tenant_id="tenant-a")
    server.add_resource(resource_b, tenant_id="tenant-b")

    resources_a = await server.list_resources(tenant_id="tenant-a")
    resources_b = await server.list_resources(tenant_id="tenant-b")
    resources_global = await server.list_resources()

    assert len(resources_a) == 1
    assert resources_a[0].name == "data-a"
    assert len(resources_b) == 1
    assert resources_b[0].name == "data-b"
    assert len(resources_global) == 0


async def test_list_resource_templates_with_tenant_id():
    """list_resource_templates filters by tenant_id."""
    server = MCPServer("test")

    def greet_a(name: str) -> str:  # pragma: no cover
        return f"Hello A, {name}!"

    def greet_b(name: str) -> str:  # pragma: no cover
        return f"Hello B, {name}!"

    server._resource_manager.add_template(
        fn=greet_a,
        uri_template="greet://{name}",
        tenant_id="tenant-a",
    )
    server._resource_manager.add_template(
        fn=greet_b,
        uri_template="greet://{name}",
        tenant_id="tenant-b",
    )

    templates_a = await server.list_resource_templates(tenant_id="tenant-a")
    templates_b = await server.list_resource_templates(tenant_id="tenant-b")
    templates_global = await server.list_resource_templates()

    assert len(templates_a) == 1
    assert len(templates_b) == 1
    assert len(templates_global) == 0


async def test_read_resource_with_tenant_id():
    """read_resource respects tenant scope."""
    server = MCPServer("test")

    resource = FunctionResource(uri="file:///secret", name="secret", fn=lambda: "secret-data")
    server.add_resource(resource, tenant_id="tenant-a")

    # Tenant A can read
    results = await server.read_resource("file:///secret", tenant_id="tenant-a")
    contents = list(results)
    assert len(contents) == 1
    assert contents[0].content == "secret-data"

    # Tenant B cannot
    from mcp.server.mcpserver.exceptions import ResourceError

    with pytest.raises(ResourceError, match="Unknown resource"):
        await server.read_resource("file:///secret", tenant_id="tenant-b")


async def test_list_prompts_with_tenant_id():
    """list_prompts filters by tenant_id."""
    server = MCPServer("test")

    async def prompt_a() -> str:  # pragma: no cover
        return "Hello from A"

    async def prompt_b() -> str:  # pragma: no cover
        return "Hello from B"

    server.add_prompt(Prompt.from_function(prompt_a, name="greet"), tenant_id="tenant-a")
    server.add_prompt(Prompt.from_function(prompt_b, name="greet"), tenant_id="tenant-b")

    prompts_a = await server.list_prompts(tenant_id="tenant-a")
    prompts_b = await server.list_prompts(tenant_id="tenant-b")
    prompts_global = await server.list_prompts()

    assert len(prompts_a) == 1
    assert len(prompts_b) == 1
    assert len(prompts_global) == 0


async def test_get_prompt_with_tenant_id():
    """get_prompt respects tenant scope."""
    server = MCPServer("test")

    async def greet_a() -> str:
        return "Hello from tenant-a"

    server.add_prompt(Prompt.from_function(greet_a, name="greet"), tenant_id="tenant-a")

    # Tenant A can get the prompt
    result = await server.get_prompt("greet", tenant_id="tenant-a")
    assert result.messages is not None
    assert len(result.messages) > 0

    # Tenant B cannot
    with pytest.raises(ValueError, match="Unknown prompt"):
        await server.get_prompt("greet", tenant_id="tenant-b")


async def test_remove_tool_with_tenant_id():
    """remove_tool respects tenant scope."""
    server = MCPServer("test")

    def my_tool() -> str:  # pragma: no cover
        return "x"

    server.add_tool(my_tool, name="my_tool", tenant_id="tenant-a")
    server.add_tool(my_tool, name="my_tool", tenant_id="tenant-b")

    server.remove_tool("my_tool", tenant_id="tenant-a")

    tools_a = await server.list_tools(tenant_id="tenant-a")
    tools_b = await server.list_tools(tenant_id="tenant-b")

    assert len(tools_a) == 0
    assert len(tools_b) == 1


# --- Backward compatibility ---


async def test_backward_compat_no_tenant_id():
    """All public methods work without tenant_id (backward compatible)."""
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    @server.resource("test://data")
    def test_resource() -> str:
        return "data"

    @server.prompt()
    def test_prompt() -> str:
        return "prompt text"

    # All operations work without tenant_id
    tools = await server.list_tools()
    assert len(tools) == 1

    result = await server.call_tool("greet", {"name": "World"})
    assert len(list(result)) > 0

    resources = await server.list_resources()
    assert len(resources) == 1

    read_result = await server.read_resource("test://data")
    assert len(list(read_result)) == 1

    prompts = await server.list_prompts()
    assert len(prompts) == 1

    prompt_result = await server.get_prompt("test_prompt")
    assert prompt_result.messages is not None
