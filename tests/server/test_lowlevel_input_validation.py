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
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import CallToolResult, ClientResult, ServerNotification, ServerRequest, TextContent, Tool


async def run_tool_test(
    tools: list[Tool],
    call_tool_handler: Callable[[str, dict[str, Any]], Awaitable[Any]],
    test_callback: Callable[[ClientSession], Awaitable[CallToolResult]],
    validate_input: bool = True,
    validate_output: bool = True,
) -> CallToolResult | None:
    """Helper to run a tool test with minimal boilerplate.

    Args:
        tools: List of tools to register
        call_tool_handler: Handler function for tool calls
        test_callback: Async function that performs the test using the client session
        validate_input: Whether to enable input validation (default: True)
        validate_output: Whether to enable output validation (default: True)

    Returns:
        The result of the tool call
    """
    server = Server("test")
    result = None

    @server.list_tools()
    async def list_tools():
        return tools

    @server.call_tool(validate_input=validate_input, validate_output=validate_output)
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await call_tool_handler(name, arguments)

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
        else:  # pragma: no cover
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

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:  # pragma: no cover
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

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:  # pragma: no cover
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
        else:  # pragma: no cover
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

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:  # pragma: no cover
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
async def test_tool_not_in_list_logs_warning(caplog: pytest.LogCaptureFixture):
    """Test that calling a tool not in list_tools logs a warning and skips validation."""
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
        # This should be reached since validation is skipped for unknown tools
        if name == "unknown_tool":
            # Even with invalid arguments, this should execute since validation is skipped
            return [TextContent(type="text", text="Unknown tool executed without validation")]
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call a tool that's not in the list with invalid arguments
        # This should trigger the warning about validation not being performed
        return await client_session.call_tool("unknown_tool", {"invalid": "args"})

    with caplog.at_level(logging.WARNING):
        result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify results - should succeed because validation is skipped for unknown tools
    assert result is not None
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Unknown tool executed without validation"

    # Verify warning was logged
    assert any(
        "Tool 'unknown_tool' not listed, no validation will be performed" in record.message for record in caplog.records
    )


@pytest.mark.anyio
async def test_validate_input_false_with_invalid_input():
    """Test that when validate_input=False, invalid input is not validated."""
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
        if name == "add":
            # Even with invalid input (string instead of number), this should execute
            # because validation is disabled
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            return [TextContent(type="text", text=f"Result: {a} + {b}")]
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call with invalid input (string instead of number)
        # With validate_input=False, this should succeed
        return await client_session.call_tool("add", {"a": "five", "b": "three"})

    result = await run_tool_test(tools, call_tool_handler, test_callback, validate_input=False)

    # Verify results - should succeed because validation is disabled
    assert result is not None
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Result: five + three"


@pytest.mark.anyio
async def test_validate_input_true_with_invalid_input():
    """Test that when validate_input=True (default), invalid input is validated."""
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
        # This should not be reached because validation will fail
        return [TextContent(type="text", text="This should not be reached")]  # pragma: no cover

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call with invalid input (string instead of number)
        # With validate_input=True (default), this should fail validation
        return await client_session.call_tool("add", {"a": "five", "b": "three"})

    result = await run_tool_test(tools, call_tool_handler, test_callback)

    # Verify error - input validation is enabled by default
    assert result is not None
    assert result.isError
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert "Input validation error" in result.content[0].text


@pytest.mark.anyio
async def test_validate_both_false():
    """Test that when both validate_input and validate_output are False, no validation occurs."""
    tools = [
        Tool(
            name="process",
            description="Process data",
            inputSchema={
                "type": "object",
                "properties": {
                    "value": {"type": "number"},
                },
                "required": ["value"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "result": {"type": "number"},
                },
                "required": ["result"],
            },
        )
    ]

    async def call_tool_handler(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "process":
            # Invalid input (string) and invalid output (string), but no validation
            value = arguments.get("value", 0)
            return {"result": f"processed_{value}"}
        else:  # pragma: no cover
            raise ValueError(f"Unknown tool: {name}")

    async def test_callback(client_session: ClientSession) -> CallToolResult:
        # Call with invalid input, and handler returns invalid output
        # With both validations disabled, server should not return error
        try:
            return await client_session.call_tool("process", {"value": "invalid"})
        except RuntimeError as e:
            # Client validation will fail, but server validation was disabled
            assert "Invalid structured content" in str(e)
            return CallToolResult(
                content=[TextContent(type="text", text="Server returned result")],
                structuredContent={"result": "processed_invalid"},
                isError=False,
            )

    result = await run_tool_test(tools, call_tool_handler, test_callback, validate_input=False, validate_output=False)

    # Verify server didn't return an error
    assert result is not None
    assert not result.isError
    assert result.structuredContent == {"result": "processed_invalid"}
