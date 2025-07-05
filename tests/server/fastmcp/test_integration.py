"""
Integration tests for FastMCP server functionality.

These tests validate the proper functioning of FastMCP features using focused,
single-feature servers across different transports (SSE and StreamableHTTP).
"""

import json
import multiprocessing
import socket
import time
from collections.abc import Generator

import pytest
import uvicorn
from pydantic import AnyUrl

from examples.snippets.servers import (
    basic_prompt,
    basic_resource,
    basic_tool,
    completion,
    elicitation,
    notifications,
    sampling,
    tool_progress,
)
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import (
    CreateMessageResult,
    ElicitResult,
    GetPromptResult,
    InitializeResult,
    LoggingMessageNotification,
    ProgressNotification,
    ReadResourceResult,
    ResourceListChangedNotification,
    ServerNotification,
    TextContent,
    TextResourceContents,
    ToolListChangedNotification,
)


class NotificationCollector:
    """Collects notifications from the server for testing."""

    def __init__(self):
        self.progress_notifications: list = []
        self.log_messages: list = []
        self.resource_notifications: list = []
        self.tool_notifications: list = []

    async def handle_generic_notification(self, message) -> None:
        """Handle any server notification and route to appropriate handler."""
        if isinstance(message, ServerNotification):
            if isinstance(message.root, ProgressNotification):
                self.progress_notifications.append(message.root.params)
            elif isinstance(message.root, LoggingMessageNotification):
                self.log_messages.append(message.root.params)
            elif isinstance(message.root, ResourceListChangedNotification):
                self.resource_notifications.append(message.root.params)
            elif isinstance(message.root, ToolListChangedNotification):
                self.tool_notifications.append(message.root.params)


# Common fixtures
@pytest.fixture
def server_port() -> int:
    """Get a free port for testing."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    """Get the server URL for testing."""
    return f"http://127.0.0.1:{server_port}"


def run_server_with_transport(module_name: str, port: int, transport: str) -> None:
    """Run server with specified transport."""
    # Get the MCP instance based on module name
    if module_name == "basic_tool":
        mcp = basic_tool.mcp
    elif module_name == "basic_resource":
        mcp = basic_resource.mcp
    elif module_name == "basic_prompt":
        mcp = basic_prompt.mcp
    elif module_name == "tool_progress":
        mcp = tool_progress.mcp
    elif module_name == "sampling":
        mcp = sampling.mcp
    elif module_name == "elicitation":
        mcp = elicitation.mcp
    elif module_name == "completion":
        mcp = completion.mcp
    elif module_name == "notifications":
        mcp = notifications.mcp
    else:
        raise ImportError(f"Unknown module: {module_name}")

    # Create app based on transport type
    if transport == "sse":
        app = mcp.sse_app()
    elif transport == "streamable-http":
        app = mcp.streamable_http_app()
    else:
        raise ValueError(f"Invalid transport for test server: {transport}")

    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error"))
    print(f"Starting {transport} server on port {port}")
    server.run()


@pytest.fixture
def server_transport(request, server_port: int) -> Generator[str, None, None]:
    """Start server in a separate process with specified MCP instance and transport.

    Args:
        request: pytest request with param tuple of (module_name, transport)
        server_port: Port to run the server on

    Yields:
        str: The transport type ('sse' or 'streamable_http')
    """
    module_name, transport = request.param

    proc = multiprocessing.Process(
        target=run_server_with_transport,
        args=(module_name, server_port, transport),
        daemon=True,
    )
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield transport

    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Server process failed to terminate")


# Helper function to create client based on transport
def create_client_for_transport(transport: str, server_url: str):
    """Create the appropriate client context manager based on transport type."""
    if transport == "sse":
        endpoint = f"{server_url}/sse"
        return sse_client(endpoint)
    elif transport == "streamable-http":
        endpoint = f"{server_url}/mcp"
        return streamablehttp_client(endpoint)
    else:
        raise ValueError(f"Invalid transport: {transport}")


def unpack_streams(client_streams):
    """Unpack client streams handling different return values from SSE vs StreamableHTTP.

    SSE client returns (read_stream, write_stream)
    StreamableHTTP client returns (read_stream, write_stream, session_id_callback)

    Args:
        client_streams: Tuple from client context manager

    Returns:
        Tuple of (read_stream, write_stream)
    """
    if len(client_streams) == 2:
        return client_streams
    else:
        read_stream, write_stream, _ = client_streams
        return read_stream, write_stream


# Callback functions for testing
async def sampling_callback(context, params) -> CreateMessageResult:
    """Sampling callback for tests."""
    return CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text",
            text="This is a simulated LLM response for testing",
        ),
        model="test-model",
    )


async def elicitation_callback(context, params):
    """Elicitation callback for tests."""
    # For restaurant booking test
    if "No tables available" in params.message:
        return ElicitResult(
            action="accept",
            content={"checkAlternative": True, "alternativeDate": "2024-12-26"},
        )
    else:
        return ElicitResult(action="decline")


# Test basic tools
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("basic_tool", "sse"),
        ("basic_tool", "streamable-http"),
    ],
    indirect=True,
)
async def test_basic_tools(server_transport: str, server_url: str) -> None:
    """Test basic tool functionality."""
    transport = server_transport
    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Tool Example"
            assert result.capabilities.tools is not None

            # Test sum tool
            tool_result = await session.call_tool("sum", {"a": 5, "b": 3})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "8"

            # Test weather tool
            weather_result = await session.call_tool("get_weather", {"city": "London"})
            assert len(weather_result.content) == 1
            assert isinstance(weather_result.content[0], TextContent)
            assert "Weather in London: 22degreesC" in weather_result.content[0].text


# Test resources
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("basic_resource", "sse"),
        ("basic_resource", "streamable-http"),
    ],
    indirect=True,
)
async def test_basic_resources(server_transport: str, server_url: str) -> None:
    """Test basic resource functionality."""
    transport = server_transport
    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Resource Example"
            assert result.capabilities.resources is not None

            # Test document resource
            doc_content = await session.read_resource(AnyUrl("file://documents/readme"))
            assert isinstance(doc_content, ReadResourceResult)
            assert len(doc_content.contents) == 1
            assert isinstance(doc_content.contents[0], TextResourceContents)
            assert "Content of readme" in doc_content.contents[0].text

            # Test settings resource
            settings_content = await session.read_resource(AnyUrl("config://settings"))
            assert isinstance(settings_content, ReadResourceResult)
            assert len(settings_content.contents) == 1
            assert isinstance(settings_content.contents[0], TextResourceContents)
            settings_json = json.loads(settings_content.contents[0].text)
            assert settings_json["theme"] == "dark"
            assert settings_json["language"] == "en"


# Test prompts
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("basic_prompt", "sse"),
        ("basic_prompt", "streamable-http"),
    ],
    indirect=True,
)
async def test_basic_prompts(server_transport: str, server_url: str) -> None:
    """Test basic prompt functionality."""
    transport = server_transport
    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Prompt Example"
            assert result.capabilities.prompts is not None

            # Test review_code prompt
            prompts = await session.list_prompts()
            review_prompt = next((p for p in prompts.prompts if p.name == "review_code"), None)
            assert review_prompt is not None

            prompt_result = await session.get_prompt("review_code", {"code": "def hello():\n    print('Hello')"})
            assert isinstance(prompt_result, GetPromptResult)
            assert len(prompt_result.messages) == 1
            assert isinstance(prompt_result.messages[0].content, TextContent)
            assert "Please review this code:" in prompt_result.messages[0].content.text
            assert "def hello():" in prompt_result.messages[0].content.text

            # Test debug_error prompt
            debug_result = await session.get_prompt(
                "debug_error", {"error": "TypeError: 'NoneType' object is not subscriptable"}
            )
            assert isinstance(debug_result, GetPromptResult)
            assert len(debug_result.messages) == 3
            assert debug_result.messages[0].role == "user"
            assert isinstance(debug_result.messages[0].content, TextContent)
            assert "I'm seeing this error:" in debug_result.messages[0].content.text
            assert debug_result.messages[1].role == "user"
            assert isinstance(debug_result.messages[1].content, TextContent)
            assert "TypeError" in debug_result.messages[1].content.text
            assert debug_result.messages[2].role == "assistant"
            assert isinstance(debug_result.messages[2].content, TextContent)
            assert "I'll help debug that" in debug_result.messages[2].content.text


# Test progress reporting
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("tool_progress", "sse"),
        ("tool_progress", "streamable-http"),
    ],
    indirect=True,
)
async def test_tool_progress(server_transport: str, server_url: str) -> None:
    """Test tool progress reporting."""
    transport = server_transport
    collector = NotificationCollector()

    async def message_handler(message):
        await collector.handle_generic_notification(message)
        if isinstance(message, Exception):
            raise message

    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Progress Example"

            # Test progress callback
            progress_updates = []

            async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
                progress_updates.append((progress, total, message))

            # Call tool with progress
            steps = 3
            tool_result = await session.call_tool(
                "long_running_task",
                {"task_name": "Test Task", "steps": steps},
                progress_callback=progress_callback,
            )

            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert "Task 'Test Task' completed" in tool_result.content[0].text

            # Verify progress updates
            assert len(progress_updates) == steps
            for i, (progress, total, message) in enumerate(progress_updates):
                expected_progress = (i + 1) / steps
                assert abs(progress - expected_progress) < 0.01
                assert total == 1.0
                assert f"Step {i + 1}/{steps}" in message

            # Verify log messages
            assert len(collector.log_messages) > 0


# Test sampling
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("sampling", "sse"),
        ("sampling", "streamable-http"),
    ],
    indirect=True,
)
async def test_sampling(server_transport: str, server_url: str) -> None:
    """Test sampling (LLM interaction) functionality."""
    transport = server_transport
    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream, sampling_callback=sampling_callback) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Sampling Example"
            assert result.capabilities.tools is not None

            # Test sampling tool
            sampling_result = await session.call_tool("generate_poem", {"topic": "nature"})
            assert len(sampling_result.content) == 1
            assert isinstance(sampling_result.content[0], TextContent)
            assert "This is a simulated LLM response" in sampling_result.content[0].text


# Test elicitation
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("elicitation", "sse"),
        ("elicitation", "streamable-http"),
    ],
    indirect=True,
)
async def test_elicitation(server_transport: str, server_url: str) -> None:
    """Test elicitation (user interaction) functionality."""
    transport = server_transport
    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream, elicitation_callback=elicitation_callback) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Elicitation Example"

            # Test booking with unavailable date (triggers elicitation)
            booking_result = await session.call_tool(
                "book_table",
                {
                    "date": "2024-12-25",  # Unavailable date
                    "time": "19:00",
                    "party_size": 4,
                },
            )
            assert len(booking_result.content) == 1
            assert isinstance(booking_result.content[0], TextContent)
            assert "[SUCCESS] Booked for 2024-12-26" in booking_result.content[0].text

            # Test booking with available date (no elicitation)
            booking_result = await session.call_tool(
                "book_table",
                {
                    "date": "2024-12-20",  # Available date
                    "time": "20:00",
                    "party_size": 2,
                },
            )
            assert len(booking_result.content) == 1
            assert isinstance(booking_result.content[0], TextContent)
            assert "[SUCCESS] Booked for 2024-12-20 at 20:00" in booking_result.content[0].text


# Test notifications
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("notifications", "sse"),
        ("notifications", "streamable-http"),
    ],
    indirect=True,
)
async def test_notifications(server_transport: str, server_url: str) -> None:
    """Test notifications and logging functionality."""
    transport = server_transport
    collector = NotificationCollector()

    async def message_handler(message):
        await collector.handle_generic_notification(message)
        if isinstance(message, Exception):
            raise message

    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Notifications Example"

            # Call tool that generates notifications
            tool_result = await session.call_tool("process_data", {"data": "test_data"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert "Processed: test_data" in tool_result.content[0].text

            # Verify log messages at different levels
            assert len(collector.log_messages) >= 4
            log_levels = {msg.level for msg in collector.log_messages}
            assert "debug" in log_levels
            assert "info" in log_levels
            assert "warning" in log_levels
            assert "error" in log_levels

            # Verify resource list changed notification
            assert len(collector.resource_notifications) > 0


# Test completion
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_transport",
    [
        ("completion", "sse"),
        ("completion", "streamable-http"),
    ],
    indirect=True,
)
async def test_completion(server_transport: str, server_url: str) -> None:
    """Test completion (autocomplete) functionality."""
    transport = server_transport
    client_cm = create_client_for_transport(transport, server_url)

    async with client_cm as client_streams:
        read_stream, write_stream = unpack_streams(client_streams)
        async with ClientSession(read_stream, write_stream) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "Example"
            assert result.capabilities.resources is not None
            assert result.capabilities.prompts is not None

            # Test resource completion
            from mcp.types import ResourceTemplateReference

            completion_result = await session.complete(
                ref=ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
                argument={"name": "repo", "value": ""},
                context_arguments={"owner": "modelcontextprotocol"},
            )

            assert completion_result is not None
            assert hasattr(completion_result, "completion")
            assert completion_result.completion is not None
            assert len(completion_result.completion.values) == 3
            assert "python-sdk" in completion_result.completion.values
            assert "typescript-sdk" in completion_result.completion.values
            assert "specification" in completion_result.completion.values

            # Test prompt completion
            from mcp.types import PromptReference

            completion_result = await session.complete(
                ref=PromptReference(type="ref/prompt", name="review_code"),
                argument={"name": "language", "value": "py"},
            )

            assert completion_result is not None
            assert hasattr(completion_result, "completion")
            assert completion_result.completion is not None
            assert "python" in completion_result.completion.values
            assert all(lang.startswith("py") for lang in completion_result.completion.values)
