"""Tests for the unified Client class."""

from __future__ import annotations

import anyio
import pytest
from inline_snapshot import snapshot

import mcp.types as types
from mcp.client.client import Client
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.types import (
    CallToolResult,
    EmptyResult,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    PromptsCapability,
    ReadResourceResult,
    Resource,
    ResourcesCapability,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
    ToolsCapability,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def simple_server() -> Server:
    """Create a simple MCP server for testing."""
    server = Server(name="test_server")

    @server.list_resources()
    async def handle_list_resources():
        return [Resource(uri="memory://test", name="Test Resource", description="A test resource")]

    @server.subscribe_resource()
    async def handle_subscribe_resource(uri: str):
        pass

    @server.unsubscribe_resource()
    async def handle_unsubscribe_resource(uri: str):
        pass

    @server.set_logging_level()
    async def handle_set_logging_level(level: str):
        pass

    @server.completion()
    async def handle_completion(
        ref: types.PromptReference | types.ResourceTemplateReference,
        argument: types.CompletionArgument,
        context: types.CompletionContext | None,
    ) -> types.Completion | None:
        return types.Completion(values=[])

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


async def test_client_is_initialized(app: FastMCP):
    """Test that the client is initialized after entering context."""
    async with Client(app) as client:
        assert client.server_capabilities == snapshot(
            ServerCapabilities(
                experimental={},
                prompts=PromptsCapability(list_changed=False),
                resources=ResourcesCapability(subscribe=False, list_changed=False),
                tools=ToolsCapability(list_changed=False),
            )
        )


async def test_client_with_simple_server(simple_server: Server):
    """Test that from_server works with a basic Server instance."""
    async with Client(simple_server) as client:
        resources = await client.list_resources()
        assert resources == snapshot(
            ListResourcesResult(
                resources=[Resource(name="Test Resource", uri="memory://test", description="A test resource")]
            )
        )


async def test_client_send_ping(app: FastMCP):
    async with Client(app) as client:
        result = await client.send_ping()
        assert result == snapshot(EmptyResult())


async def test_client_list_tools(app: FastMCP):
    async with Client(app) as client:
        result = await client.list_tools()
        assert result == snapshot(
            ListToolsResult(
                tools=[
                    Tool(
                        name="greet",
                        description="Greet someone by name.",
                        input_schema={
                            "properties": {"name": {"title": "Name", "type": "string"}},
                            "required": ["name"],
                            "title": "greetArguments",
                            "type": "object",
                        },
                        output_schema={
                            "properties": {"result": {"title": "Result", "type": "string"}},
                            "required": ["result"],
                            "title": "greetOutput",
                            "type": "object",
                        },
                    ),
                    Tool(
                        name="add",
                        description="Add two numbers.",
                        input_schema={
                            "properties": {
                                "a": {"title": "A", "type": "integer"},
                                "b": {"title": "B", "type": "integer"},
                            },
                            "required": ["a", "b"],
                            "title": "addArguments",
                            "type": "object",
                        },
                        output_schema={
                            "properties": {"result": {"title": "Result", "type": "integer"}},
                            "required": ["result"],
                            "title": "addOutput",
                            "type": "object",
                        },
                    ),
                ]
            )
        )


async def test_client_call_tool(app: FastMCP):
    async with Client(app) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(text="Hello, World!")],
                structured_content={"result": "Hello, World!"},
            )
        )


async def test_read_resource(app: FastMCP):
    """Test reading a resource."""
    async with Client(app) as client:
        result = await client.read_resource("test://resource")
        assert result == snapshot(
            ReadResourceResult(
                contents=[TextResourceContents(uri="test://resource", mime_type="text/plain", text="Test content")]
            )
        )


async def test_get_prompt(app: FastMCP):
    """Test getting a prompt."""
    async with Client(app) as client:
        result = await client.get_prompt("greeting_prompt", {"name": "Alice"})
        assert result == snapshot(
            GetPromptResult(
                description="A greeting prompt.",
                messages=[PromptMessage(role="user", content=TextContent(text="Please greet Alice warmly."))],
            )
        )


def test_client_session_property_before_enter(app: FastMCP):
    """Test that accessing session before context manager raises RuntimeError."""
    client = Client(app)
    with pytest.raises(RuntimeError, match="Client must be used within an async context manager"):
        client.session


async def test_client_reentry_raises_runtime_error(app: FastMCP):
    """Test that reentering a client raises RuntimeError."""
    async with Client(app) as client:
        with pytest.raises(RuntimeError, match="Client is already entered"):
            await client.__aenter__()


async def test_client_send_progress_notification():
    """Test sending progress notification."""
    received_from_client = None
    event = anyio.Event()
    server = Server(name="test_server")

    @server.progress_notification()
    async def handle_progress_notification(
        progress_token: str | int,
        progress: float = 0.0,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        nonlocal received_from_client
        received_from_client = {"progress_token": progress_token, "progress": progress}
        event.set()

    async with Client(server) as client:
        await client.send_progress_notification(progress_token="token123", progress=50.0)
        await event.wait()
        assert received_from_client == snapshot({"progress_token": "token123", "progress": 50.0})


async def test_client_subscribe_resource(simple_server: Server):
    async with Client(simple_server) as client:
        result = await client.subscribe_resource("memory://test")
        assert result == snapshot(EmptyResult())


async def test_client_unsubscribe_resource(simple_server: Server):
    async with Client(simple_server) as client:
        result = await client.unsubscribe_resource("memory://test")
        assert result == snapshot(EmptyResult())


async def test_client_set_logging_level(simple_server: Server):
    """Test setting logging level."""
    async with Client(simple_server) as client:
        result = await client.set_logging_level("debug")
        assert result == snapshot(EmptyResult())


async def test_client_list_resources_with_params(app: FastMCP):
    """Test listing resources with params parameter."""
    async with Client(app) as client:
        result = await client.list_resources()
        assert result == snapshot(
            ListResourcesResult(
                resources=[
                    Resource(
                        name="test_resource",
                        uri="test://resource",
                        description="A test resource.",
                        mime_type="text/plain",
                    )
                ]
            )
        )


async def test_client_list_resource_templates(app: FastMCP):
    """Test listing resource templates with params parameter."""
    async with Client(app) as client:
        result = await client.list_resource_templates()
        assert result == snapshot(ListResourceTemplatesResult(resource_templates=[]))


async def test_list_prompts(app: FastMCP):
    """Test listing prompts with params parameter."""
    async with Client(app) as client:
        result = await client.list_prompts()
        assert result == snapshot(
            ListPromptsResult(
                prompts=[
                    Prompt(
                        name="greeting_prompt",
                        description="A greeting prompt.",
                        arguments=[PromptArgument(name="name", required=True)],
                    )
                ]
            )
        )


async def test_complete_with_prompt_reference(simple_server: Server):
    """Test getting completions for a prompt argument."""
    async with Client(simple_server) as client:
        ref = types.PromptReference(type="ref/prompt", name="test_prompt")
        result = await client.complete(ref=ref, argument={"name": "arg", "value": "test"})
        assert result == snapshot(types.CompleteResult(completion=types.Completion(values=[])))
