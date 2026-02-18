"""Test dependency injection integration with tools."""

# pyright: reportUnknownMemberType=false, reportArgumentType=false
import pytest

from mcp.client import Client
from mcp.server import Depends
from mcp.server.mcpserver import MCPServer


@pytest.mark.anyio
async def test_tool_with_dependency():
    """Test that tools can receive dependencies via Depends()."""

    # Setup
    def get_constant() -> str:
        return "injected_value"

    server = MCPServer("test-server")

    @server.tool()
    async def use_dependency(arg: int, value: str = Depends(get_constant)) -> str:
        return f"{arg}:{value}"

    # Test
    async with Client(server) as client:
        result = await client.call_tool("use_dependency", {"arg": 42})
        assert result.content[0].text == "42:injected_value"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.anyio
async def test_nested_dependencies():
    """Test that dependencies can depend on other dependencies."""

    def get_base() -> int:
        return 10

    def get_derived(base: int = Depends(get_base)) -> int:
        return base * 2

    server = MCPServer("test-server")

    @server.tool()
    async def use_nested(value: int = Depends(get_derived)) -> int:
        return value + 5

    async with Client(server) as client:
        result = await client.call_tool("use_nested", {})
        # Should be (10 * 2) + 5 = 25
        # The result is wrapped in structured output as {'result': 25}
        assert result.structured_content == {"result": 25}


@pytest.mark.anyio
async def test_dependency_override():
    """Test that dependencies can be overridden for testing."""

    def get_value() -> str:
        return "production"

    def get_test_value() -> str:
        return "test"

    server = MCPServer("test-server")

    @server.tool()
    async def show_value(value: str = Depends(get_value)) -> str:
        return value

    # Override for testing
    server.override_dependency(get_value, get_test_value)

    async with Client(server) as client:
        result = await client.call_tool("show_value", {})
        assert result.content[0].text == "test"


@pytest.mark.anyio
async def test_multiple_dependencies():
    """Test that tools can use multiple dependencies."""

    def get_first() -> str:
        return "first"

    def get_second() -> int:
        return 42

    server = MCPServer("test-server")

    @server.tool()
    async def use_multiple(
        first: str = Depends(get_first),
        second: int = Depends(get_second),
    ) -> str:
        return f"{first}:{second}"

    async with Client(server) as client:
        result = await client.call_tool("use_multiple", {})
        assert result.content[0].text == "first:42"


@pytest.mark.anyio
async def test_dependency_with_regular_args():
    """Test that dependencies work alongside regular arguments."""

    def get_prefix() -> str:
        return "prefix"

    server = MCPServer("test-server")

    @server.tool()
    async def combine(prefix: str = Depends(get_prefix), suffix: str = "") -> str:
        return f"{prefix}:{suffix}"

    async with Client(server) as client:
        result = await client.call_tool("combine", {"suffix": "suffix"})
        assert result.content[0].text == "prefix:suffix"


@pytest.mark.anyio
async def test_async_dependency():
    """Test that async dependency functions work."""

    async def get_async_value() -> str:
        return "async_value"

    server = MCPServer("test-server")

    @server.tool()
    async def use_async_dep(value: str = Depends(get_async_value)) -> str:
        return value

    async with Client(server) as client:
        result = await client.call_tool("use_async_dep", {})
        assert result.content[0].text == "async_value"


@pytest.mark.anyio
async def test_dependency_caching_per_request():
    """Test that dependencies are cached within a single request."""

    call_count = 0

    def get_cached_value() -> str:
        nonlocal call_count
        call_count += 1
        return "cached"

    server = MCPServer("test-server")

    @server.tool()
    async def use_cached_twice(
        first: str = Depends(get_cached_value),
        second: str = Depends(get_cached_value),
    ) -> str:
        # Both should get the same cached instance
        return f"{first}:{second}"

    async with Client(server) as client:
        result = await client.call_tool("use_cached_twice", {})
        assert result.content[0].text == "cached:cached"
        # Should only call once due to caching
        assert call_count == 1
