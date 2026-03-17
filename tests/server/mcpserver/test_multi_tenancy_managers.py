"""Tests for tenant-scoped storage in ToolManager, ResourceManager, and PromptManager."""

import pytest

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.prompts.base import Prompt
from mcp.server.mcpserver.prompts.manager import PromptManager
from mcp.server.mcpserver.resources.resource_manager import ResourceManager
from mcp.server.mcpserver.resources.types import FunctionResource
from mcp.server.mcpserver.tools import ToolManager
from tests.server.mcpserver.conftest import MakeContext

# --- ToolManager ---


def test_add_tool_with_tenant_id():
    """Tools added under different tenants are isolated."""
    manager = ToolManager()

    def tool_a() -> str:  # pragma: no cover
        return "a"

    def tool_b() -> str:  # pragma: no cover
        return "b"

    manager.add_tool(tool_a, name="shared_name", tenant_id="tenant-a")
    manager.add_tool(tool_b, name="shared_name", tenant_id="tenant-b")

    assert manager.get_tool("shared_name", tenant_id="tenant-a") is not None
    assert manager.get_tool("shared_name", tenant_id="tenant-b") is not None
    # Different tool objects despite same name
    assert manager.get_tool("shared_name", tenant_id="tenant-a") is not manager.get_tool(
        "shared_name", tenant_id="tenant-b"
    )


def test_list_tools_filtered_by_tenant():
    """list_tools only returns tools for the requested tenant."""
    manager = ToolManager()

    def fa() -> str:  # pragma: no cover
        return "a"

    def fb() -> str:  # pragma: no cover
        return "b"

    def fc() -> str:  # pragma: no cover
        return "c"

    manager.add_tool(fa, tenant_id="tenant-a")
    manager.add_tool(fb, tenant_id="tenant-b")
    manager.add_tool(fc)  # global (None tenant)

    assert len(manager.list_tools(tenant_id="tenant-a")) == 1
    assert len(manager.list_tools(tenant_id="tenant-b")) == 1
    assert len(manager.list_tools()) == 1  # global only


def test_get_tool_wrong_tenant_returns_none():
    """A tool registered under tenant-a is not visible to tenant-b."""
    manager = ToolManager()

    def my_tool() -> str:  # pragma: no cover
        return "x"

    manager.add_tool(my_tool, tenant_id="tenant-a")

    assert manager.get_tool("my_tool", tenant_id="tenant-a") is not None
    assert manager.get_tool("my_tool", tenant_id="tenant-b") is None
    assert manager.get_tool("my_tool") is None  # global scope


def test_remove_tool_with_tenant():
    """remove_tool respects tenant scope."""
    manager = ToolManager()

    def my_tool() -> str:  # pragma: no cover
        return "x"

    manager.add_tool(my_tool, tenant_id="tenant-a")
    manager.add_tool(my_tool, name="my_tool", tenant_id="tenant-b")

    manager.remove_tool("my_tool", tenant_id="tenant-a")

    assert manager.get_tool("my_tool", tenant_id="tenant-a") is None
    assert manager.get_tool("my_tool", tenant_id="tenant-b") is not None
    # Empty tenant scope is cleaned up
    assert "tenant-a" not in manager._tools


def test_remove_tool_wrong_tenant_raises():
    """Removing a tool under the wrong tenant raises ToolError."""
    manager = ToolManager()

    def my_tool() -> str:  # pragma: no cover
        return "x"

    manager.add_tool(my_tool, tenant_id="tenant-a")

    with pytest.raises(ToolError):
        manager.remove_tool("my_tool", tenant_id="tenant-b")


@pytest.mark.anyio
async def test_call_tool_with_tenant(make_context: MakeContext):
    """call_tool respects tenant scope."""
    manager = ToolManager()

    def tool_a() -> str:
        return "result-a"

    def tool_b() -> str:
        return "result-b"

    manager.add_tool(tool_a, name="do_work", tenant_id="tenant-a")
    manager.add_tool(tool_b, name="do_work", tenant_id="tenant-b")

    result_a = await manager.call_tool("do_work", {}, make_context(), tenant_id="tenant-a")
    result_b = await manager.call_tool("do_work", {}, make_context(), tenant_id="tenant-b")

    assert result_a == "result-a"
    assert result_b == "result-b"


@pytest.mark.anyio
async def test_call_tool_wrong_tenant_raises(make_context: MakeContext):
    """Calling a tool under the wrong tenant raises ToolError."""
    manager = ToolManager()

    def my_tool() -> str:  # pragma: no cover
        return "x"

    manager.add_tool(my_tool, tenant_id="tenant-a")

    with pytest.raises(ToolError):
        await manager.call_tool("my_tool", {}, make_context(), tenant_id="tenant-b")


# --- ResourceManager ---


def _make_resource(uri: str, name: str) -> FunctionResource:
    """Helper to create a concrete resource."""
    return FunctionResource(uri=uri, name=name, fn=lambda: name)


def test_add_resource_with_tenant():
    """Resources added under different tenants are isolated."""
    manager = ResourceManager()

    resource_a = _make_resource("file:///data", "data-a")
    resource_b = _make_resource("file:///data", "data-b")

    added_a = manager.add_resource(resource_a, tenant_id="tenant-a")
    added_b = manager.add_resource(resource_b, tenant_id="tenant-b")

    assert added_a.name == "data-a"
    assert added_b.name == "data-b"


def test_list_resources_filtered_by_tenant():
    """list_resources only returns resources for the requested tenant."""
    manager = ResourceManager()

    manager.add_resource(_make_resource("file:///a", "a"), tenant_id="tenant-a")
    manager.add_resource(_make_resource("file:///b", "b"), tenant_id="tenant-b")
    manager.add_resource(_make_resource("file:///g", "global"))

    assert len(manager.list_resources(tenant_id="tenant-a")) == 1
    assert len(manager.list_resources(tenant_id="tenant-b")) == 1
    assert len(manager.list_resources()) == 1


def test_add_template_with_tenant():
    """Templates added under different tenants are isolated."""
    manager = ResourceManager()

    def greet_a(name: str) -> str:  # pragma: no cover
        return f"Hello from A, {name}!"

    def greet_b(name: str) -> str:  # pragma: no cover
        return f"Hello from B, {name}!"

    manager.add_template(greet_a, uri_template="greet://{name}", tenant_id="tenant-a")
    manager.add_template(greet_b, uri_template="greet://{name}", tenant_id="tenant-b")

    assert len(manager.list_templates(tenant_id="tenant-a")) == 1
    assert len(manager.list_templates(tenant_id="tenant-b")) == 1
    assert len(manager.list_templates()) == 0  # no global templates


@pytest.mark.anyio
async def test_get_resource_respects_tenant(make_context: MakeContext):
    """get_resource only finds resources in the correct tenant scope."""
    manager = ResourceManager()

    resource = _make_resource("file:///secret", "secret")
    manager.add_resource(resource, tenant_id="tenant-a")

    # Tenant A can access
    found = await manager.get_resource("file:///secret", make_context(), tenant_id="tenant-a")
    assert found.name == "secret"

    # Tenant B cannot
    with pytest.raises(ValueError, match="Unknown resource"):
        await manager.get_resource("file:///secret", make_context(), tenant_id="tenant-b")

    # Global scope cannot
    with pytest.raises(ValueError, match="Unknown resource"):
        await manager.get_resource("file:///secret", make_context())


@pytest.mark.anyio
async def test_get_resource_from_template_respects_tenant(make_context: MakeContext):
    """Template-based resource creation respects tenant scope."""
    manager = ResourceManager()

    def greet(name: str) -> str:
        return f"Hello, {name}!"

    manager.add_template(greet, uri_template="greet://{name}", tenant_id="tenant-a")

    # Tenant A can resolve
    resource = await manager.get_resource("greet://world", make_context(), tenant_id="tenant-a")
    assert isinstance(resource, FunctionResource)
    content = await resource.read()
    assert content == "Hello, world!"

    # Tenant B cannot
    with pytest.raises(ValueError, match="Unknown resource"):
        await manager.get_resource("greet://world", make_context(), tenant_id="tenant-b")


def test_remove_resource_with_tenant():
    """remove_resource respects tenant scope."""
    manager = ResourceManager()

    manager.add_resource(_make_resource("file:///data", "data"), tenant_id="tenant-a")
    manager.add_resource(_make_resource("file:///data", "data"), tenant_id="tenant-b")

    manager.remove_resource("file:///data", tenant_id="tenant-a")

    assert len(manager.list_resources(tenant_id="tenant-a")) == 0
    assert len(manager.list_resources(tenant_id="tenant-b")) == 1
    # Empty tenant scope is cleaned up
    assert "tenant-a" not in manager._resources


def test_remove_resource_wrong_tenant_raises():
    """Removing a resource under the wrong tenant raises ValueError."""
    manager = ResourceManager()
    manager.add_resource(_make_resource("file:///data", "data"), tenant_id="tenant-a")

    with pytest.raises(ValueError, match="Unknown resource"):
        manager.remove_resource("file:///data", tenant_id="tenant-b")


# --- PromptManager ---


def _make_prompt(name: str, text: str) -> Prompt:
    """Helper to create a simple prompt."""

    async def fn() -> str:  # pragma: no cover
        return text

    return Prompt.from_function(fn, name=name)


def test_add_prompt_with_tenant():
    """Prompts added under different tenants are isolated."""
    manager = PromptManager()

    prompt_a = _make_prompt("greet", "Hello from A")
    prompt_b = _make_prompt("greet", "Hello from B")

    manager.add_prompt(prompt_a, tenant_id="tenant-a")
    manager.add_prompt(prompt_b, tenant_id="tenant-b")

    assert manager.get_prompt("greet", tenant_id="tenant-a") is prompt_a
    assert manager.get_prompt("greet", tenant_id="tenant-b") is prompt_b


def test_list_prompts_filtered_by_tenant():
    """list_prompts only returns prompts for the requested tenant."""
    manager = PromptManager()

    manager.add_prompt(_make_prompt("a", "A"), tenant_id="tenant-a")
    manager.add_prompt(_make_prompt("b", "B"), tenant_id="tenant-b")
    manager.add_prompt(_make_prompt("g", "Global"))

    assert len(manager.list_prompts(tenant_id="tenant-a")) == 1
    assert len(manager.list_prompts(tenant_id="tenant-b")) == 1
    assert len(manager.list_prompts()) == 1


def test_get_prompt_wrong_tenant_returns_none():
    """A prompt registered under tenant-a is not visible to tenant-b."""
    manager = PromptManager()
    manager.add_prompt(_make_prompt("secret", "x"), tenant_id="tenant-a")

    assert manager.get_prompt("secret", tenant_id="tenant-a") is not None
    assert manager.get_prompt("secret", tenant_id="tenant-b") is None
    assert manager.get_prompt("secret") is None


@pytest.mark.anyio
async def test_render_prompt_respects_tenant(make_context: MakeContext):
    """render_prompt only finds prompts in the correct tenant scope."""
    manager = PromptManager()

    async def greet() -> str:
        return "Hello from tenant-a"

    manager.add_prompt(Prompt.from_function(greet, name="greet"), tenant_id="tenant-a")

    # Tenant A can render
    messages = await manager.render_prompt("greet", None, make_context(), tenant_id="tenant-a")
    assert len(messages) > 0

    # Tenant B cannot
    with pytest.raises(ValueError, match="Unknown prompt"):
        await manager.render_prompt("greet", None, make_context(), tenant_id="tenant-b")


def test_remove_prompt_with_tenant():
    """remove_prompt respects tenant scope."""
    manager = PromptManager()

    manager.add_prompt(_make_prompt("greet", "A"), tenant_id="tenant-a")
    manager.add_prompt(_make_prompt("greet", "B"), tenant_id="tenant-b")

    manager.remove_prompt("greet", tenant_id="tenant-a")

    assert manager.get_prompt("greet", tenant_id="tenant-a") is None
    assert manager.get_prompt("greet", tenant_id="tenant-b") is not None
    # Empty tenant scope is cleaned up
    assert "tenant-a" not in manager._prompts


def test_remove_prompt_wrong_tenant_raises():
    """Removing a prompt under the wrong tenant raises ValueError."""
    manager = PromptManager()
    manager.add_prompt(_make_prompt("greet", "A"), tenant_id="tenant-a")

    with pytest.raises(ValueError, match="Unknown prompt"):
        manager.remove_prompt("greet", tenant_id="tenant-b")
