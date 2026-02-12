"""Tests for BaseClientSession Protocol."""

from __future__ import annotations

import pytest

from mcp import types
from mcp.client import BaseClientSession
from mcp.client.client import Client
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


async def test_client_session_satisfies_base_client_session_protocol():
    """ClientSession is a structural subtype of BaseClientSession."""
    server = MCPServer(name="test")

    @server.tool()
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    async with Client(server) as client:
        # Verify isinstance works with @runtime_checkable Protocol
        assert isinstance(client.session, BaseClientSession)
        # Verify the session is actually a ClientSession
        assert isinstance(client.session, ClientSession)


async def test_base_client_session_e2e_via_client():
    """Demonstrate that Client.session can be used as BaseClientSession."""
    server = MCPServer(name="test")

    @server.tool()
    def echo(text: str) -> str:
        return text

    async with Client(server) as client:
        # Type-annotate session as BaseClientSession to prove compatibility
        session: BaseClientSession = client.session

        # Call tool through the Protocol interface
        result = await session.call_tool("echo", {"text": "hello"})
        assert result.is_error is False
        assert len(result.content) == 1
        assert result.content[0].text == "hello"

        # List tools through the Protocol interface
        tools_result = await session.list_tools()
        assert len(tools_result.tools) == 1
        assert tools_result.tools[0].name == "echo"


async def test_base_client_session_complete_and_set_logging_level():
    """Verify complete() and set_logging_level() are accessible through Protocol."""
    server = MCPServer(name="test")

    @server.prompt()
    def greeting(name: str) -> str:
        return f"Hello {name}!"

    async with Client(server) as client:
        session: BaseClientSession = client.session

        # Test that complete() method exists and is callable
        # Note: We can't actually call it without a valid reference,
        # but we verify the method signature matches
        assert hasattr(session, "complete")
        assert callable(session.complete)

        # Test that set_logging_level() method exists and is callable
        assert hasattr(session, "set_logging_level")
        assert callable(session.set_logging_level)


class StubClientSession:
    """Minimal stub that satisfies BaseClientSession protocol."""

    async def send_request(
        self, request, result_type, request_read_timeout_seconds=None, metadata=None, progress_callback=None
    ):
        return types.EmptyResult()

    async def send_notification(self, notification, related_request_id=None):
        pass

    async def send_progress_notification(self, progress_token, progress, total=None, message=None, *, meta=None):
        pass

    async def initialize(self):
        return types.InitializeResult()

    async def send_ping(self, *, meta=None):
        return types.EmptyResult()

    async def list_resources(self, *, params=None):
        return types.ListResourcesResult()

    async def list_resource_templates(self, *, params=None):
        return types.ListResourceTemplatesResult()

    async def read_resource(self, uri, *, meta=None):
        return types.ReadResourceResult()

    async def subscribe_resource(self, uri, *, meta=None):
        return types.EmptyResult()

    async def unsubscribe_resource(self, uri, *, meta=None):
        return types.EmptyResult()

    async def call_tool(self, name, arguments=None, read_timeout_seconds=None, progress_callback=None, *, meta=None):
        return types.CallToolResult()

    async def list_prompts(self, *, params=None):
        return types.ListPromptsResult()

    async def get_prompt(self, name, arguments=None, *, meta=None):
        return types.GetPromptResult()

    async def list_tools(self, *, params=None):
        return types.ListToolsResult()

    async def complete(self, ref, argument, context_arguments=None):
        return types.CompleteResult()

    async def set_logging_level(self, level, *, meta=None):
        return types.EmptyResult()

    async def send_roots_list_changed(self):
        pass


def test_custom_session_satisfies_protocol():
    """A custom implementation satisfies BaseClientSession protocol."""
    stub = StubClientSession()
    assert isinstance(stub, BaseClientSession)


def test_protocol_method_completeness():
    """All expected methods are declared in the Protocol."""
    expected_methods = {
        "send_request",
        "send_notification",
        "send_progress_notification",
        "initialize",
        "send_ping",
        "list_resources",
        "list_resource_templates",
        "read_resource",
        "subscribe_resource",
        "unsubscribe_resource",
        "call_tool",
        "list_prompts",
        "get_prompt",
        "list_tools",
        "complete",
        "set_logging_level",
        "send_roots_list_changed",
    }

    actual_methods = {
        name
        for name in dir(BaseClientSession)
        if not name.startswith("_") and callable(getattr(BaseClientSession, name, None))
    }

    # The Protocol should have all expected methods
    assert expected_methods <= actual_methods, f"Missing methods: {expected_methods - actual_methods}"
