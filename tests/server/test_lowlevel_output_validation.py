"""Test output schema validation for lowlevel server."""

import json
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
    async def message_handler(  # pragma: no cover
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
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


@pytest.mark.anyio
async def test_content_only_without_output_schema():
    """Test returning content only when no outputSchema is defined."""
    tools = [
        Tool(
            name="echo",
            description="Echo a message",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
                "required": ["message"],
            },
            # No outputSchema defined
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "echo":
            assert params.arguments is not None
            return CallToolResult(content=[TextContent(type="text", text=f"Echo: {params.arguments['message']}")])
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("echo", {"message": "Hello"})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Echo: Hello"
    assert result.structured_content is None


@pytest.mark.anyio
async def test_dict_only_without_output_schema():
    """Test returning dict as structured_content when no outputSchema is defined."""
    tools = [
        Tool(
            name="get_info",
            description="Get structured information",
            input_schema={
                "type": "object",
                "properties": {},
            },
            # No outputSchema defined
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "get_info":
            data: dict[str, Any] = {"status": "ok", "data": {"value": 42}}
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(data))],
                structured_content=data,
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("get_info", {})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    # Check that the content is the JSON serialization
    assert json.loads(result.content[0].text) == {"status": "ok", "data": {"value": 42}}
    assert result.structured_content == {"status": "ok", "data": {"value": 42}}


@pytest.mark.anyio
async def test_both_content_and_dict_without_output_schema():
    """Test returning both content and structured_content when no outputSchema is defined."""
    tools = [
        Tool(
            name="process",
            description="Process data",
            input_schema={
                "type": "object",
                "properties": {},
            },
            # No outputSchema defined
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "process":
            return CallToolResult(
                content=[TextContent(type="text", text="Processing complete")],
                structured_content={"result": "success", "count": 10},
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("process", {})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Processing complete"
    assert result.structured_content == {"result": "success", "count": 10}


@pytest.mark.anyio
async def test_content_only_with_output_schema_error():
    """Test that returning content without structured_content when outputSchema is defined results in error.

    Note: With the new low-level server API, handlers return CallToolResult directly.
    The handler is responsible for returning the appropriate error when outputSchema
    requirements are not met.
    """
    tools = [
        Tool(
            name="structured_tool",
            description="Tool expecting structured output",
            input_schema={
                "type": "object",
                "properties": {},
            },
            output_schema={
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                },
                "required": ["result"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        # This returns only content, but outputSchema expects structured data
        # With the new API, the handler is responsible for validation
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Output validation error: outputSchema defined but no structured output returned",
                )
            ],
            is_error=True,
        )

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("structured_tool", {})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify error
    assert result is not None
    assert result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Output validation error: outputSchema defined but no structured output returned" in result.content[0].text


@pytest.mark.anyio
async def test_valid_dict_with_output_schema():
    """Test valid dict output matching outputSchema."""
    tools = [
        Tool(
            name="calc",
            description="Calculate result",
            input_schema={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["x", "y"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "sum": {"type": "number"},
                    "product": {"type": "number"},
                },
                "required": ["sum", "product"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "calc":
            assert params.arguments is not None
            x = params.arguments["x"]
            y = params.arguments["y"]
            data: dict[str, Any] = {"sum": x + y, "product": x * y}
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(data))],
                structured_content=data,
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("calc", {"x": 3, "y": 4})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    # Check JSON serialization
    assert json.loads(result.content[0].text) == {"sum": 7, "product": 12}
    assert result.structured_content == {"sum": 7, "product": 12}


@pytest.mark.anyio
async def test_invalid_dict_with_output_schema():
    """Test dict output that doesn't match outputSchema.

    Note: With the new low-level server API, handlers return CallToolResult directly.
    The handler is responsible for returning the appropriate error when outputSchema
    validation fails.
    """
    tools = [
        Tool(
            name="user_info",
            description="Get user information",
            input_schema={
                "type": "object",
                "properties": {},
            },
            output_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name", "age"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "user_info":
            # Missing required 'age' field - handler reports the error
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Output validation error: 'age' is a required property",
                    )
                ],
                is_error=True,
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("user_info", {})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify error
    assert result is not None
    assert result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Output validation error:" in result.content[0].text
    assert "'age' is a required property" in result.content[0].text


@pytest.mark.anyio
async def test_both_content_and_valid_dict_with_output_schema():
    """Test returning both content and valid structured_content with outputSchema."""
    tools = [
        Tool(
            name="analyze",
            description="Analyze data",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["sentiment", "confidence"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "analyze":
            assert params.arguments is not None
            return CallToolResult(
                content=[TextContent(type="text", text=f"Analysis of: {params.arguments['text']}")],
                structured_content={"sentiment": "positive", "confidence": 0.95},
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("analyze", {"text": "Great job!"})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Analysis of: Great job!"
    assert result.structured_content == {"sentiment": "positive", "confidence": 0.95}


@pytest.mark.anyio
async def test_tool_call_result():
    """Test returning CallToolResult directly."""
    tools = [
        Tool(
            name="get_info",
            description="Get structured information",
            input_schema={
                "type": "object",
                "properties": {},
            },
            # No outputSchema for direct return of tool call result
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "get_info":
            return CallToolResult(
                content=[TextContent(type="text", text="Results calculated")],
                structured_content={"status": "ok", "data": {"value": 42}},
                _meta={"some": "metadata"},
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("get_info", {})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Results calculated"
    assert isinstance(result.content[0], TextContent)
    assert result.structured_content == {"status": "ok", "data": {"value": 42}}
    assert result.meta == {"some": "metadata"}


@pytest.mark.anyio
async def test_output_schema_type_validation():
    """Test outputSchema validates types correctly.

    Note: With the new low-level server API, handlers return CallToolResult directly.
    The handler is responsible for returning the appropriate error when outputSchema
    validation fails.
    """
    tools = [
        Tool(
            name="stats",
            description="Get statistics",
            input_schema={
                "type": "object",
                "properties": {},
            },
            output_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "average": {"type": "number"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["count", "average", "items"],
            },
        )
    ]

    async def call_tool_handler(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "stats":
            # Wrong type for 'count' - should be integer, handler reports the error
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Output validation error: 'five' is not of type 'integer'",
                    )
                ],
                is_error=True,
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {params.name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("stats", {})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify error
    assert result is not None
    assert result.is_error
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert "Output validation error:" in result.content[0].text
    assert "'five' is not of type 'integer'" in result.content[0].text
