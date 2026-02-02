"""Tests for the unified Client class."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import anyio
import pytest
from inline_snapshot import snapshot

import mcp.types as types
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
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

    async def handle_list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[Resource(uri="memory://test", name="Test Resource", description="A test resource")]
        )

    async def handle_subscribe_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.SubscribeRequestParams,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def handle_unsubscribe_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.UnsubscribeRequestParams,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def handle_set_logging_level(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.SetLevelRequestParams,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def handle_completion(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.CompleteRequestParams,
    ) -> types.CompleteResult:
        return types.CompleteResult(completion=types.Completion(values=[]))

    server = Server(
        name="test_server",
        on_list_resources=handle_list_resources,
        on_subscribe_resource=handle_subscribe_resource,
        on_unsubscribe_resource=handle_unsubscribe_resource,
        on_set_logging_level=handle_set_logging_level,
        on_completion=handle_completion,
    )

    return server


@pytest.fixture
def app() -> MCPServer:
    """Create an MCPServer server for testing."""
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"Hello, {name}!"

    @server.resource("test://resource")
    def test_resource() -> str:
        """A test resource."""
        return "Test content"

    @server.prompt()
    def greeting_prompt(name: str) -> str:
        """A greeting prompt."""
        return f"Please greet {name} warmly."

    return server


async def test_client_is_initialized(app: MCPServer):
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


async def test_client_send_ping(app: MCPServer):
    async with Client(app) as client:
        result = await client.send_ping()
        assert result == snapshot(EmptyResult())


async def test_client_list_tools(app: MCPServer):
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
                    )
                ]
            )
        )


async def test_client_call_tool(app: MCPServer):
    async with Client(app) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(text="Hello, World!")],
                structured_content={"result": "Hello, World!"},
            )
        )


async def test_read_resource(app: MCPServer):
    """Test reading a resource."""
    async with Client(app) as client:
        result = await client.read_resource("test://resource")
        assert result == snapshot(
            ReadResourceResult(
                contents=[TextResourceContents(uri="test://resource", mime_type="text/plain", text="Test content")]
            )
        )


async def test_get_prompt(app: MCPServer):
    """Test getting a prompt."""
    async with Client(app) as client:
        result = await client.get_prompt("greeting_prompt", {"name": "Alice"})
        assert result == snapshot(
            GetPromptResult(
                description="A greeting prompt.",
                messages=[PromptMessage(role="user", content=TextContent(text="Please greet Alice warmly."))],
            )
        )


def test_client_session_property_before_enter(app: MCPServer):
    """Test that accessing session before context manager raises RuntimeError."""
    client = Client(app)
    with pytest.raises(RuntimeError, match="Client must be used within an async context manager"):
        client.session


async def test_client_reentry_raises_runtime_error(app: MCPServer):
    """Test that reentering a client raises RuntimeError."""
    async with Client(app) as client:
        with pytest.raises(RuntimeError, match="Client is already entered"):
            await client.__aenter__()


async def test_client_send_progress_notification():
    """Test sending progress notification."""
    received_from_client = None
    event = anyio.Event()

    async def handle_progress_notification(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ProgressNotificationParams,
    ) -> None:
        nonlocal received_from_client
        received_from_client = {"progress_token": params.progress_token, "progress": params.progress}
        event.set()

    server = Server(name="test_server", on_progress_notification=handle_progress_notification)

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


async def test_client_list_resources_with_params(app: MCPServer):
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


async def test_client_list_resource_templates(app: MCPServer):
    """Test listing resource templates with params parameter."""
    async with Client(app) as client:
        result = await client.list_resource_templates()
        assert result == snapshot(ListResourceTemplatesResult(resource_templates=[]))


async def test_list_prompts(app: MCPServer):
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


def test_client_with_url_initializes_streamable_http_transport():
    with patch("mcp.client.client.streamable_http_client") as mock:
        _ = Client("http://localhost:8000/mcp")
    mock.assert_called_once_with("http://localhost:8000/mcp")


async def test_client_uses_transport_directly(app: MCPServer):
    transport = InMemoryTransport(app)
    async with Client(transport) as client:
        result = await client.call_tool("greet", {"name": "Transport"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(text="Hello, Transport!")],
                structured_content={"result": "Hello, Transport!"},
            )
        )
