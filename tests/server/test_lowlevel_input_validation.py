"""Test input schema validation for lowlevel server."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ClientResult,
    ListToolsResult,
    PaginatedRequestParams,
    ServerNotification,
    ServerRequest,
    TextContent,
    Tool,
)


async def run_tool_test(
    tools: list[Tool],
    call_tool_handler: Callable[[ServerRequestContext, CallToolRequestParams], Awaitable[CallToolResult]],
    test_callback: Callable[[ClientSession], Awaitable[CallToolResult]],
) -> CallToolResult | None:
    """Helper to run a tool test with minimal boilerplate.

    Args:
        tools: List of tools to register
        call_tool_handler: Handler function for tool calls
        test_callback: Async function that performs the test using the client session

    Returns:
        The result of the tool call
    """

    async def handle_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    server = Server("test", on_list_tools=handle_list_tools, on_call_tool=call_tool_handler)
    result = None

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Message handler for client
    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    # Server task
    async def run_server():
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        ) as server_session:
            async with anyio.create_task_group() as tg:

                async def handle_messages():
                    async for message in server_session.incoming_messages:  # pragma: no branch
                        await server._handle_message(message, server_session, {}, False)

                tg.start_soon(handle_messages)
                await anyio.sleep_forever()

    # Run the test
    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            # Initialize the session
            await client_session.initialize()

            # Run the test callback
            result = await test_callback(client_session)

            # Cancel the server task
            tg.cancel_scope.cancel()

    return result


def create_add_tool() -> Tool:
    """Create a standard 'add' tool for testing."""
    return Tool(
        name="add",
        description="Add two numbers",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    )


@pytest.mark.anyio
async def test_valid_tool_call():
    """Test that valid arguments pass validation."""

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "add":
            assert params.arguments is not None
            result = params.arguments["a"] + params.arguments["b"]
            return CallToolResult(content=[TextContent(type="text", text=f"Result: {result}")])
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("add", {"a": 5, "b": 3})

    result = await run_tool_test([create_add_tool()], call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Result: 8"


@pytest.mark.anyio
async def test_invalid_tool_call_missing_required():
    """Test that missing required arguments fail validation.

    Note: With the new low-level server API, input validation is the handler's
    responsibility. The handler returns an error CallToolResult for invalid input.
    """

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        # Handler performs its own validation
        arguments = params.arguments or {}
        if "a" not in arguments or "b" not in arguments:
            missing = [k for k in ["a", "b"] if k not in arguments]
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Input validation error: '{missing[0]}' is a required property",
                    )
                ],
                is_error=True,
            )
        result = arguments["a"] + arguments["b"]  # pragma: no cover
        return CallToolResult(content=[TextContent(type="text", text=f"Result: {result}")])  # pragma: no cover

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("add", {"a": 5})  # missing 'b'

    result = await run_tool_test([create_add_tool()], call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Input validation error" in result.content[0].text
    assert "'b' is a required property" in result.content[0].text


@pytest.mark.anyio
async def test_invalid_tool_call_wrong_type():
    """Test that wrong argument types fail validation.

    Note: With the new low-level server API, input validation is the handler's
    responsibility.
    """

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        # Handler performs its own validation
        arguments = params.arguments or {}
        for key in ["a", "b"]:
            if key in arguments and not isinstance(arguments[key], (int, float)):
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"Input validation error: '{arguments[key]}' is not of type 'number'",
                        )
                    ],
                    is_error=True,
                )
        result = arguments["a"] + arguments["b"]  # pragma: no cover
        return CallToolResult(content=[TextContent(type="text", text=f"Result: {result}")])  # pragma: no cover

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("add", {"a": "five", "b": 3})  # 'a' should be number

    result = await run_tool_test([create_add_tool()], call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Input validation error" in result.content[0].text
    assert "'five' is not of type 'number'" in result.content[0].text


@pytest.mark.anyio
async def test_cache_refresh_on_missing_tool():
    """Test that tool call works even without listing tools first."""
    tools = [
        Tool(
            name="multiply",
            description="Multiply two numbers",
            input_schema={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["x", "y"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "multiply":
            assert params.arguments is not None
            result = params.arguments["x"] * params.arguments["y"]
            return CallToolResult(content=[TextContent(type="text", text=f"Result: {result}")])
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call tool without first listing tools (cache should be empty)
        # The cache should be refreshed automatically
        return await client_session.call_tool("multiply", {"x": 10, "y": 20})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results - should work because cache will be refreshed
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Result: 200"


@pytest.mark.anyio
async def test_enum_constraint_validation():
    """Test that enum constraints are validated.

    Note: With the new low-level server API, input validation is the handler's
    responsibility.
    """
    tools = [
        Tool(
            name="greet",
            description="Greet someone",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "title": {"type": "string", "enum": ["Mr", "Ms", "Dr"]},
                },
                "required": ["name"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        # Handler performs its own validation
        arguments = params.arguments or {}
        valid_titles = ["Mr", "Ms", "Dr"]
        if "title" in arguments and arguments["title"] not in valid_titles:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Input validation error: '{arguments['title']}' is not one of {valid_titles}",
                    )
                ],
                is_error=True,
            )
        return CallToolResult(  # pragma: no cover
            content=[TextContent(type="text", text=f"Hello {arguments.get('title', '')} {arguments['name']}")]
        )

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("greet", {"name": "Smith", "title": "Prof"})  # Invalid title

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Input validation error" in result.content[0].text
    assert "'Prof' is not one of" in result.content[0].text


@pytest.mark.anyio
async def test_tool_not_in_list_logs_warning(caplog: pytest.LogCaptureFixture):
    """Test that calling a tool not in list_tools still works."""
    tools = [
        Tool(
            name="add",
            description="Add two numbers",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        # This should be reached since the handler handles all tool calls
        if params.name == "unknown_tool":
            return CallToolResult(content=[TextContent(type="text", text="Unknown tool executed without validation")])
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call a tool that's not in the list with invalid arguments
        return await client_session.call_tool("unknown_tool", {"invalid": "args"})

    with caplog.at_level(logging.WARNING):
        result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results - should succeed because handler handles all calls
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Unknown tool executed without validation"
