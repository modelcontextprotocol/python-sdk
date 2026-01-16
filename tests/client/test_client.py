"""Tests for the unified Client class."""

from unittest.mock import AsyncMock, patch

import pytest

import mcp.types as types
from mcp.client.client import Client
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.types import EmptyResult, Resource

pytestmark = pytest.mark.anyio


@pytest.fixture
def simple_server() -> Server:
    """Create a simple MCP server for testing."""
    server = Server(name="test_server")

    @server.list_resources()
    async def handle_list_resources():
        return [
            Resource(
                uri="memory://test",
                name="Test Resource",
                description="A test resource",
            )
        ]

    return server


@pytest.fixture
def app() -> FastMCP:
    """Create a FastMCP server for testing."""
    server = FastMCP("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"Hello, {name}!"

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @server.resource("test://resource")
    def test_resource() -> str:
        """A test resource."""
        return "Test content"

    @server.prompt()
    def greeting_prompt(name: str) -> str:
        """A greeting prompt."""
        return f"Please greet {name} warmly."

    return server


async def test_creates_client(app: FastMCP):
    """Test that from_server creates a connected client."""
    async with Client(app) as client:
        assert client is not None


async def test_client_is_initialized(app: FastMCP):
    """Test that the client is initialized after entering context."""
    async with Client(app) as client:
        caps = client.server_capabilities
        assert caps is not None
        assert caps.tools is not None


async def test_with_simple_server(simple_server: Server):
    """Test that from_server works with a basic Server instance."""
    async with Client(simple_server) as client:
        assert client is not None
        caps = client.server_capabilities
        assert caps is not None
        # Verify list_resources works and returns expected resource
        resources = await client.list_resources()
        assert len(resources.resources) == 1
        assert resources.resources[0].uri == "memory://test"


async def test_ping_returns_empty_result(app: FastMCP):
    """Test that ping returns an EmptyResult."""
    async with Client(app) as client:
        result = await client.send_ping()
        assert isinstance(result, EmptyResult)


async def test_list_tools(app: FastMCP):
    """Test listing tools."""
    async with Client(app) as client:
        result = await client.list_tools()
        assert result.tools is not None
        tool_names = [t.name for t in result.tools]
        assert "greet" in tool_names
        assert "add" in tool_names


async def test_list_tools_with_pagination(app: FastMCP):
    """Test listing tools with pagination params."""
    from mcp.types import PaginatedRequestParams

    async with Client(app) as client:
        result = await client.list_tools(params=PaginatedRequestParams())
        assert result.tools is not None


async def test_call_tool(app: FastMCP):
    """Test calling a tool."""
    async with Client(app) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result.content is not None
        assert len(result.content) > 0
        content_str = str(result.content[0])
        assert "Hello, World!" in content_str


async def test_call_tool_with_multiple_args(app: FastMCP):
    """Test calling a tool with multiple arguments."""
    async with Client(app) as client:
        result = await client.call_tool("add", {"a": 5, "b": 3})
        assert result.content is not None
        content_str = str(result.content[0])
        assert "8" in content_str


async def test_list_resources(app: FastMCP):
    """Test listing resources."""
    async with Client(app) as client:
        result = await client.list_resources()
        # FastMCP may have different resource listing behavior
        assert result is not None


async def test_read_resource(app: FastMCP):
    """Test reading a resource."""
    async with Client(app) as client:
        result = await client.read_resource("test://resource")
        assert result.contents is not None
        assert len(result.contents) > 0


async def test_list_prompts(app: FastMCP):
    """Test listing prompts."""
    async with Client(app) as client:
        result = await client.list_prompts()
        prompt_names = [p.name for p in result.prompts]
        assert "greeting_prompt" in prompt_names


async def test_get_prompt(app: FastMCP):
    """Test getting a prompt."""
    async with Client(app) as client:
        result = await client.get_prompt("greeting_prompt", {"name": "Alice"})
        assert result.messages is not None
        assert len(result.messages) > 0


async def test_session_property(app: FastMCP):
    """Test that the session property returns the ClientSession."""
    from mcp.client.session import ClientSession

    async with Client(app) as client:
        session = client.session
        assert isinstance(session, ClientSession)


async def test_session_is_same_as_internal(app: FastMCP):
    """Test that session property returns consistent instance."""
    async with Client(app) as client:
        session1 = client.session
        session2 = client.session
        assert session1 is session2


async def test_enters_and_exits_cleanly(app: FastMCP):
    """Test that the client enters and exits cleanly."""
    async with Client(app) as client:
        # Should be able to use client
        await client.send_ping()
    # After exiting, resources should be cleaned up


async def test_exception_during_use(app: FastMCP):
    """Test that exceptions during use don't prevent cleanup."""
    with pytest.raises(Exception):  # May be wrapped in ExceptionGroup by anyio
        async with Client(app) as client:
            await client.send_ping()
            raise ValueError("Test exception")
    # Should exit cleanly despite exception


async def test_aexit_without_aenter(app: FastMCP):
    """Test that calling __aexit__ without __aenter__ doesn't raise."""
    client = Client(app)
    # This should not raise even though __aenter__ was never called
    await client.__aexit__(None, None, None)
    assert client._session is None


async def test_server_capabilities_after_init(app: FastMCP):
    """Test server_capabilities property after initialization."""
    async with Client(app) as client:
        caps = client.server_capabilities
        assert caps is not None
        # FastMCP should advertise tools capability
        assert caps.tools is not None


def test_session_property_before_enter(app: FastMCP):
    """Test that accessing session before context manager raises RuntimeError."""
    client = Client(app)
    with pytest.raises(RuntimeError, match="Client must be used within an async context manager"):
        _ = client.session


async def test_reentry_raises_runtime_error(app: FastMCP):
    """Test that reentering a client raises RuntimeError."""
    async with Client(app) as client:
        with pytest.raises(RuntimeError, match="Client is already entered"):
            await client.__aenter__()


async def test_cleanup_on_init_failure(app: FastMCP):
    """Test that resources are cleaned up if initialization fails."""
    with patch("mcp.client.client.ClientSession") as mock_session_class:
        # Create a mock context manager that fails on __aenter__
        mock_session = AsyncMock()
        mock_session.__aenter__.side_effect = RuntimeError("Session init failed")
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_class.return_value = mock_session

        client = Client(app)
        with pytest.raises(BaseException) as exc_info:
            await client.__aenter__()

        # The error should contain our message (may be wrapped in ExceptionGroup)
        # Use repr() to see nested exceptions in ExceptionGroup
        assert "Session init failed" in repr(exc_info.value)

        # Verify the client is in a clean state (session should be None)
        assert client._session is None


async def test_send_progress_notification(app: FastMCP):
    """Test sending progress notification."""
    async with Client(app) as client:
        # Send a progress notification - this should not raise
        await client.send_progress_notification(
            progress_token="test-token",
            progress=50.0,
            total=100.0,
            message="Half done",
        )


async def test_subscribe_resource(app: FastMCP):
    """Test subscribing to a resource."""
    async with Client(app) as client:
        # Mock the session's subscribe_resource since FastMCP doesn't support it
        with patch.object(client.session, "subscribe_resource", return_value=EmptyResult()):
            result = await client.subscribe_resource("test://resource")
            assert isinstance(result, EmptyResult)


async def test_unsubscribe_resource(app: FastMCP):
    """Test unsubscribing from a resource."""
    async with Client(app) as client:
        # Mock the session's unsubscribe_resource since FastMCP doesn't support it
        with patch.object(client.session, "unsubscribe_resource", return_value=EmptyResult()):
            result = await client.unsubscribe_resource("test://resource")
            assert isinstance(result, EmptyResult)


async def test_send_roots_list_changed(app: FastMCP):
    """Test sending roots list changed notification."""
    async with Client(app) as client:
        # Send roots list changed notification - should not raise
        await client.send_roots_list_changed()


async def test_set_logging_level(app: FastMCP):
    """Test setting logging level."""
    async with Client(app) as client:
        # Mock the session's set_logging_level since FastMCP doesn't support it
        with patch.object(client.session, "set_logging_level", return_value=EmptyResult()):
            result = await client.set_logging_level("debug")
            assert isinstance(result, EmptyResult)


async def test_list_resources_with_params(app: FastMCP):
    """Test listing resources with params parameter."""
    async with Client(app) as client:
        result = await client.list_resources(params=types.PaginatedRequestParams())
        assert result is not None


async def test_list_resource_templates_with_params(app: FastMCP):
    """Test listing resource templates with params parameter."""
    async with Client(app) as client:
        result = await client.list_resource_templates(params=types.PaginatedRequestParams())
        assert result is not None


async def test_list_resource_templates_default(app: FastMCP):
    """Test listing resource templates with no params or cursor."""
    async with Client(app) as client:
        result = await client.list_resource_templates()
        assert result is not None


async def test_list_prompts_with_params(app: FastMCP):
    """Test listing prompts with params parameter."""
    async with Client(app) as client:
        result = await client.list_prompts(params=types.PaginatedRequestParams())
        assert result is not None


async def test_complete_with_prompt_reference(app: FastMCP):
    """Test getting completions for a prompt argument."""
    async with Client(app) as client:
        ref = types.PromptReference(type="ref/prompt", name="greeting_prompt")
        # Mock the session's complete method since FastMCP may not support it
        with patch.object(
            client.session,
            "complete",
            return_value=types.CompleteResult(completion=types.Completion(values=[])),
        ):
            result = await client.complete(ref=ref, argument={"name": "test"})
            assert result is not None
