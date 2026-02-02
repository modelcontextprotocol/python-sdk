"""Tests for constructor-based handler registration in the low-level Server class."""

from typing import Any

import pytest

import mcp.types as types
from mcp.client.client import Client
from mcp.server import Server
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext

pytestmark = pytest.mark.anyio


async def test_constructor_list_tools_handler():
    """Test registering list_tools via constructor."""

    async def list_tools(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="test-tool", description="A test tool", input_schema={"type": "object"})]
        )

    server = Server(
        name="test-server",
        on_list_tools=list_tools,
    )

    assert types.ListToolsRequest in server.request_handlers


async def test_constructor_call_tool_handler():
    """Test registering call_tool via constructor."""

    async def call_tool(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Called {params.name}")],
        )

    server = Server(
        name="test-server",
        on_call_tool=call_tool,
    )

    assert types.CallToolRequest in server.request_handlers


async def test_constructor_list_prompts_handler():
    """Test registering list_prompts via constructor."""

    async def list_prompts(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[types.Prompt(name="test-prompt", description="A test prompt")])

    server = Server(
        name="test-server",
        on_list_prompts=list_prompts,
    )

    assert types.ListPromptsRequest in server.request_handlers


async def test_constructor_get_prompt_handler():
    """Test registering get_prompt via constructor."""

    async def get_prompt(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.GetPromptRequestParams,
    ) -> types.GetPromptResult:
        return types.GetPromptResult(
            messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text="Hello"))]
        )

    server = Server(
        name="test-server",
        on_get_prompt=get_prompt,
    )

    assert types.GetPromptRequest in server.request_handlers


async def test_constructor_list_resources_handler():
    """Test registering list_resources via constructor."""

    async def list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[types.Resource(uri="test://resource", name="Test Resource")])

    server = Server(
        name="test-server",
        on_list_resources=list_resources,
    )

    assert types.ListResourcesRequest in server.request_handlers


async def test_constructor_read_resource_handler():
    """Test registering read_resource via constructor."""

    async def read_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=params.uri, mime_type="text/plain", text="content")]
        )

    server = Server(
        name="test-server",
        on_read_resource=read_resource,
    )

    assert types.ReadResourceRequest in server.request_handlers


async def test_constructor_list_resource_templates_handler():
    """Test registering list_resource_templates via constructor."""

    async def list_resource_templates(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=[types.ResourceTemplate(uri_template="test://{id}", name="Test Template")]
        )

    server = Server(
        name="test-server",
        on_list_resource_templates=list_resource_templates,
    )

    assert types.ListResourceTemplatesRequest in server.request_handlers


async def test_constructor_subscribe_resource_handler():
    """Test registering subscribe_resource via constructor."""

    async def subscribe_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.SubscribeRequestParams,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    server = Server(
        name="test-server",
        on_subscribe_resource=subscribe_resource,
    )

    assert types.SubscribeRequest in server.request_handlers


async def test_constructor_unsubscribe_resource_handler():
    """Test registering unsubscribe_resource via constructor."""

    async def unsubscribe_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.UnsubscribeRequestParams,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    server = Server(
        name="test-server",
        on_unsubscribe_resource=unsubscribe_resource,
    )

    assert types.UnsubscribeRequest in server.request_handlers


async def test_constructor_set_logging_level_handler():
    """Test registering set_logging_level via constructor."""

    async def set_logging_level(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.SetLevelRequestParams,
    ) -> types.EmptyResult:
        return types.EmptyResult()

    server = Server(
        name="test-server",
        on_set_logging_level=set_logging_level,
    )

    assert types.SetLevelRequest in server.request_handlers


async def test_constructor_completion_handler():
    """Test registering completion via constructor."""

    async def completion(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.CompleteRequestParams,
    ) -> types.CompleteResult:
        return types.CompleteResult(completion=types.Completion(values=["test"]))

    server = Server(
        name="test-server",
        on_completion=completion,
    )

    assert types.CompleteRequest in server.request_handlers


async def test_constructor_progress_notification_handler():
    """Test registering progress_notification via constructor."""

    async def progress_notification(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ProgressNotificationParams,
    ) -> None:
        pass

    server = Server(
        name="test-server",
        on_progress_notification=progress_notification,
    )

    assert types.ProgressNotification in server.notification_handlers


async def test_constructor_tools_e2e():
    """E2E test for constructor-based tool handlers."""

    async def list_tools(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="echo",
                    description="Echo input",
                    input_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                )
            ]
        )

    async def call_tool(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        if params.name == "echo":
            msg = (params.arguments or {}).get("message", "")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=msg)],
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {params.name}")],
            is_error=True,
        )

    server = Server(
        name="test-server",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )

    async with Client(server) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 1
        assert tools.tools[0].name == "echo"

        result = await client.call_tool("echo", {"message": "hello"})
        assert result.content[0].text == "hello"  # type: ignore[union-attr]


async def test_constructor_prompts_e2e():
    """E2E test for constructor-based prompt handlers."""

    async def list_prompts(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[types.Prompt(name="greeting", description="A greeting prompt")])

    async def get_prompt(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.GetPromptRequestParams,
    ) -> types.GetPromptResult:
        if params.name == "greeting":
            name = (params.arguments or {}).get("name", "World")
            return types.GetPromptResult(
                messages=[
                    types.PromptMessage(role="user", content=types.TextContent(type="text", text=f"Hello, {name}!"))
                ]
            )
        raise ValueError(f"Unknown prompt: {params.name}")

    server = Server(
        name="test-server",
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )

    async with Client(server) as client:
        prompts = await client.list_prompts()
        assert len(prompts.prompts) == 1
        assert prompts.prompts[0].name == "greeting"

        result = await client.get_prompt("greeting", {"name": "Alice"})
        assert len(result.messages) == 1
        assert result.messages[0].content.text == "Hello, Alice!"  # type: ignore[union-attr]


async def test_constructor_resources_e2e():
    """E2E test for constructor-based resource handlers."""

    async def list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[types.Resource(uri="test://resource", name="Test Resource")])

    async def read_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        if params.uri == "test://resource":
            return types.ReadResourceResult(
                contents=[types.TextResourceContents(uri=params.uri, mime_type="text/plain", text="Resource content")]
            )
        raise ValueError(f"Unknown resource: {params.uri}")

    server = Server(
        name="test-server",
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )

    async with Client(server) as client:
        resources = await client.list_resources()
        assert len(resources.resources) == 1
        assert resources.resources[0].name == "Test Resource"

        result = await client.read_resource("test://resource")
        assert len(result.contents) == 1
        assert result.contents[0].text == "Resource content"  # type: ignore[union-attr]


async def test_constructor_all_handlers():
    """Test registering all handlers via constructor."""

    async def list_prompts(
        ctx: RequestContext[ServerSession, Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    async def get_prompt(
        ctx: RequestContext[ServerSession, Any, Any], params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        return types.GetPromptResult(messages=[])

    async def list_resources(
        ctx: RequestContext[ServerSession, Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    async def list_resource_templates(
        ctx: RequestContext[ServerSession, Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(resource_templates=[])

    async def read_resource(
        ctx: RequestContext[ServerSession, Any, Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(contents=[])

    async def subscribe_resource(
        ctx: RequestContext[ServerSession, Any, Any], params: types.SubscribeRequestParams
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def unsubscribe_resource(
        ctx: RequestContext[ServerSession, Any, Any], params: types.UnsubscribeRequestParams
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def list_tools(
        ctx: RequestContext[ServerSession, Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    async def call_tool(
        ctx: RequestContext[ServerSession, Any, Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        return types.CallToolResult(content=[])

    async def set_logging_level(
        ctx: RequestContext[ServerSession, Any, Any], params: types.SetLevelRequestParams
    ) -> types.EmptyResult:
        return types.EmptyResult()

    async def completion(
        ctx: RequestContext[ServerSession, Any, Any], params: types.CompleteRequestParams
    ) -> types.CompleteResult:
        return types.CompleteResult(completion=types.Completion(values=[]))

    async def progress_notification(
        ctx: RequestContext[ServerSession, Any, Any], params: types.ProgressNotificationParams
    ) -> None:
        pass

    server = Server(
        name="test-server",
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
        on_list_resources=list_resources,
        on_list_resource_templates=list_resource_templates,
        on_read_resource=read_resource,
        on_subscribe_resource=subscribe_resource,
        on_unsubscribe_resource=unsubscribe_resource,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_set_logging_level=set_logging_level,
        on_completion=completion,
        on_progress_notification=progress_notification,
    )

    # Verify all request handlers are registered
    assert types.ListPromptsRequest in server.request_handlers
    assert types.GetPromptRequest in server.request_handlers
    assert types.ListResourcesRequest in server.request_handlers
    assert types.ListResourceTemplatesRequest in server.request_handlers
    assert types.ReadResourceRequest in server.request_handlers
    assert types.SubscribeRequest in server.request_handlers
    assert types.UnsubscribeRequest in server.request_handlers
    assert types.ListToolsRequest in server.request_handlers
    assert types.CallToolRequest in server.request_handlers
    assert types.SetLevelRequest in server.request_handlers
    assert types.CompleteRequest in server.request_handlers
    assert types.ProgressNotification in server.notification_handlers
