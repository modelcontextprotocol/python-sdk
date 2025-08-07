"""Test input schema validation for lowlevel server."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    METHOD_NOT_FOUND,
    CallToolResult,
    ClientResult,
    ErrorData,
    ServerNotification,
    ServerRequest,
    TextContent,
    Tool,
)


async def run_tool_test(
    tools: list[Tool],
    call_tool_handler: Callable[[str, dict[str, Any]], Awaitable[list[TextContent]]],
    test_callback: Callable[[ClientSession], Awaitable[Any]],
) -> Any:
    """Helper to run a tool test with minimal boilerplate.

    Args:
        tools: List of tools to register
        call_tool_handler: Handler function for tool calls
        test_callback: Async function that performs the test using the client session

    Returns:
        The result of the tool call
    """
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await call_tool_handler(name, arguments)

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Message handler for client
    async def message_handler(
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
                    async for message in server_session.incoming_messages:
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
        inputSchema={
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

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "add":
            result = arguments["a"] + arguments["b"]
            return [TextContent(type="text", text=f"Result: {result}")]
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("add", {"a": 5, "b": 3})

    result = await run_tool_test([create_add_tool()], call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Result: 8"


@pytest.mark.anyio
async def test_invalid_tool_call_missing_required():
    """Test that missing required arguments fail validation."""

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # This should not be reached due to validation
        raise RuntimeError("Should not reach here")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("add", {"a": 5})  # missing 'b'

    result = await run_tool_test([create_add_tool()], call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Input validation error" in result.content[0].text
    assert "'b' is a required property" in result.content[0].text


@pytest.mark.anyio
async def test_invalid_tool_call_wrong_type():
    """Test that wrong argument types fail validation."""

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # This should not be reached due to validation
        raise RuntimeError("Should not reach here")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("add", {"a": "five", "b": 3})  # 'a' should be number

    result = await run_tool_test([create_add_tool()], call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Input validation error" in result.content[0].text
    assert "'five' is not of type 'number'" in result.content[0].text


@pytest.mark.anyio
async def test_cache_refresh_on_missing_tool():
    """Test that tool cache is refreshed when tool is not found."""
    tools = [
        Tool(
            name="multiply",
            description="Multiply two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["x", "y"],
            },
        )
    ]

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "multiply":
            result = arguments["x"] * arguments["y"]
            return [TextContent(type="text", text=f"Result: {result}")]
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call tool without first listing tools (cache should be empty)
        # The cache should be refreshed automatically
        return await client_session.call_tool("multiply", {"x": 10, "y": 20})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results - should work because cache will be refreshed
    assert result is not None
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Result: 200"


@pytest.mark.anyio
async def test_enum_constraint_validation():
    """Test that enum constraints are validated."""
    tools = [
        Tool(
            name="greet",
            description="Greet someone",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "title": {"type": "string", "enum": ["Mr", "Ms", "Dr"]},
                },
                "required": ["name"],
            },
        )
    ]

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # This should not be reached due to validation failure
        raise RuntimeError("Should not reach here")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        return await client_session.call_tool("greet", {"name": "Smith", "title": "Prof"})  # Invalid title

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results
    assert result is not None
    assert result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert "Input validation error" in result.content[0].text
    assert "'Prof' is not one of" in result.content[0].text


@pytest.mark.anyio
async def test_tool_not_in_list_logs_warning_before_protocol_error(caplog):
    """Test that calling a tool not in list_tools logs a warning before returning protocol error."""

    tools = [
        Tool(
            name="add",
            description="Add two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        )
    ]

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # This should not be reached due to protocol error for unknown tools
        if name == "add":
            result = arguments["a"] + arguments["b"]
            return [TextContent(type="text", text=f"Result: {result}")]
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession):
        # Call a tool that's not in the list - should now raise McpError
        try:
            return await client_session.call_tool("unknown_tool", {"invalid": "args"})
        except McpError as e:
            return e

    with caplog.at_level(logging.WARNING):
        result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify it's the correct protocol error
    assert isinstance(result, McpError), f"Expected McpError but got {type(result)}"
    assert isinstance(result.error, ErrorData)
    assert result.error.code == METHOD_NOT_FOUND
    assert "Unknown tool: unknown_tool" in result.error.message

    # Verify warning was still logged during the tool lookup process
    assert any(
        "Tool 'unknown_tool' not listed, no validation will be performed" in record.message for record in caplog.records
    )


@pytest.mark.anyio
async def test_unknown_tool_returns_protocol_error():
    """Test that calling an unknown tool returns a proper JSON-RPC protocol error."""

    tools = [
        Tool(
            name="add",
            description="Add two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        )
    ]

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # This should not be reached for unknown tools due to protocol error
        if name == "add":
            result = arguments["a"] + arguments["b"]
            return [TextContent(type="text", text=f"Result: {result}")]
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession):
        # Try to call a tool that doesn't exist - should raise McpError
        try:
            return await client_session.call_tool("unknown_tool", {"invalid": "args"})
        except McpError as e:
            return e

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify it's the correct protocol error
    assert isinstance(result, McpError), f"Expected McpError but got {type(result)}"
    assert isinstance(result.error, ErrorData)
    assert result.error.code == METHOD_NOT_FOUND
    assert "Unknown tool: unknown_tool" in result.error.message


@pytest.mark.anyio
async def test_tool_execution_error_vs_protocol_error():
    """Test the difference between tool execution errors and protocol errors."""

    tools = [
        Tool(
            name="failing_tool",
            description="A tool that always fails during execution",
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                },
            },
        )
    ]

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "failing_tool":
            # This should cause a tool execution error (not a protocol error)
            raise RuntimeError("Tool execution failed")
        else:
            raise ValueError(f"Unknown tool: {name}")

    # Test 1: Tool execution error (valid tool that fails)
    async def test_execution_error(client_session: ClientSession):
        return await client_session.call_tool("failing_tool", {"input": "test"})

    execution_result = await run_tool_test(tools, call_tool_handler, test_execution_error)

    # Should return CallToolResult with isError=True (tool execution error)
    assert isinstance(execution_result, CallToolResult)
    assert execution_result.isError
    assert isinstance(execution_result.content[0], TextContent)
    assert "Tool execution failed" in execution_result.content[0].text

    # Test 2: Protocol error (unknown tool)
    async def test_protocol_error(client_session: ClientSession):
        try:
            return await client_session.call_tool("nonexistent_tool", {"input": "test"})
        except McpError as e:
            return e

    protocol_result = await run_tool_test(tools, call_tool_handler, test_protocol_error)

    # Should return McpError (protocol error)
    assert isinstance(protocol_result, McpError), f"Expected McpError but got {type(protocol_result)}"
    assert isinstance(protocol_result.error, ErrorData)
    assert protocol_result.error.code == METHOD_NOT_FOUND
    assert "Unknown tool: nonexistent_tool" in protocol_result.error.message
