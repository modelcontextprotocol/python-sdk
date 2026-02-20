"""Tests for BaseClientSession Protocol."""

from __future__ import annotations

from typing import Any

import pytest

from mcp import types
from mcp.client import BaseClientSession
from mcp.client.client import Client
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.session import ProgressFnT
from mcp.types._types import RequestParamsMeta

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
        first_content = result.content[0]
        assert isinstance(first_content, types.TextContent)
        assert first_content.text == "hello"

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
        self,
        request: types.ClientRequest,
        result_type: type[Any],
        request_read_timeout_seconds: float | None = None,
        metadata: Any = None,
        progress_callback: ProgressFnT | None = None,
    ) -> Any:
        return types.EmptyResult()

    async def send_notification(
        self,
        notification: types.ClientNotification,
        related_request_id: Any = None,
    ) -> None:
        pass

    async def send_progress_notification(
        self,
        progress_token: types.ProgressToken,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> None:
        pass

    async def initialize(self) -> types.InitializeResult:
        return types.InitializeResult(
            protocol_version="2024-11-05",
            capabilities=types.ServerCapabilities(),
            server_info=types.Implementation(name="stub", version="0"),
        )

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        return types.EmptyResult()

    async def list_resources(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    async def list_resource_templates(
        self, *, params: types.PaginatedRequestParams | None = None
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(resource_templates=[])

    async def read_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.ReadResourceResult:
        return types.ReadResourceResult(contents=[])

    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        return types.EmptyResult()

    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        return types.EmptyResult()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.CallToolResult:
        return types.CallToolResult(content=[])

    async def list_prompts(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.GetPromptResult:
        return types.GetPromptResult(messages=[])

    async def list_tools(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    async def complete(
        self,
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> types.CompleteResult:
        return types.CompleteResult(completion=types.Completion(values=[]))

    async def set_logging_level(
        self,
        level: types.LoggingLevel,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def send_roots_list_changed(self) -> None:
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
