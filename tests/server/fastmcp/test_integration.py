"""
Integration tests for FastMCP server functionality.

These tests validate the proper functioning of FastMCP in various configurations,
including with and without authentication.
"""

import multiprocessing
import socket
import time
from collections.abc import Generator

import pytest
import uvicorn
from pydantic import AnyUrl

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from mcp.shared.context import RequestContext
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    GetPromptResult,
    InitializeResult,
    ReadResourceResult,
    SamplingMessage,
    TextContent,
    TextResourceContents,
)


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


@pytest.fixture
def http_server_port() -> int:
    """Get a free port for testing the StreamableHTTP server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server_url(http_server_port: int) -> str:
    """Get the StreamableHTTP server URL for testing."""
    return f"http://127.0.0.1:{http_server_port}"


@pytest.fixture
def stateless_http_server_port() -> int:
    """Get a free port for testing the stateless StreamableHTTP server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def stateless_http_server_url(stateless_http_server_port: int) -> str:
    """Get the stateless StreamableHTTP server URL for testing."""
    return f"http://127.0.0.1:{stateless_http_server_port}"


# Create a function to make the FastMCP server app
def make_fastmcp_app():
    """Create a FastMCP server without auth settings."""
    from starlette.applications import Starlette

    mcp = FastMCP(name="NoAuthServer")

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the SSE app
    app: Starlette = mcp.sse_app()

    return mcp, app


def make_everything_fastmcp() -> FastMCP:
    """Create a FastMCP server with all features enabled for testing."""
    from mcp.server.fastmcp import Context

    mcp = FastMCP(name="EverythingServer")

    # Tool with context for logging and progress
    @mcp.tool(description="A tool that demonstrates logging and progress")
    async def tool_with_progress(message: str, ctx: Context, steps: int = 3) -> str:
        await ctx.info(f"Starting processing of '{message}' with {steps} steps")

        # Send progress notifications
        for i in range(steps):
            progress_value = (i + 1) / steps
            await ctx.report_progress(
                progress=progress_value,
                total=1.0,
                message=f"Processing step {i + 1} of {steps}",
            )
            await ctx.debug(f"Completed step {i + 1}")

        return f"Processed '{message}' in {steps} steps"

    # Simple tool for basic functionality
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Tool with sampling capability
    @mcp.tool(description="A tool that uses sampling to generate content")
    async def sampling_tool(prompt: str, ctx: Context) -> str:
        await ctx.info(f"Requesting sampling for prompt: {prompt}")

        # Request sampling from the client
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user", content=TextContent(type="text", text=prompt)
                )
            ],
            max_tokens=100,
            temperature=0.7,
        )

        await ctx.info(f"Received sampling result from model: {result.model}")
        # Handle different content types
        if result.content.type == "text":
            return f"Sampling result: {result.content.text[:100]}..."
        else:
            return f"Sampling result: {str(result.content)[:100]}..."

    # Tool that sends notifications and logging
    @mcp.tool(description="A tool that demonstrates notifications and logging")
    async def notification_tool(message: str, ctx: Context) -> str:
        # Send different log levels
        await ctx.debug("Debug: Starting notification tool")
        await ctx.info(f"Info: Processing message '{message}'")
        await ctx.warning("Warning: This is a test warning")

        # Send resource change notifications
        await ctx.session.send_resource_list_changed()
        await ctx.session.send_tool_list_changed()

        await ctx.info("Completed notification tool successfully")
        return f"Sent notifications and logs for: {message}"

    # Resource - static
    def get_static_info() -> str:
        return "This is static resource content"

    static_resource = FunctionResource(
        uri=AnyUrl("resource://static/info"),
        name="Static Info",
        description="Static information resource",
        fn=get_static_info,
    )
    mcp.add_resource(static_resource)

    # Resource - dynamic function
    @mcp.resource("resource://dynamic/{category}")
    def dynamic_resource(category: str) -> str:
        return f"Dynamic resource content for category: {category}"

    # Resource template
    @mcp.resource("resource://template/{id}/data")
    def template_resource(id: str) -> str:
        return f"Template resource data for ID: {id}"

    # Prompt - simple
    @mcp.prompt(description="A simple prompt")
    def simple_prompt(topic: str) -> str:
        return f"Tell me about {topic}"

    # Prompt - complex with multiple messages
    @mcp.prompt(description="Complex prompt with context")
    def complex_prompt(user_query: str, context: str = "general") -> str:
        # For simplicity, return a single string that incorporates the context
        # Since FastMCP doesn't support system messages in the same way
        return f"Context: {context}. Query: {user_query}"

    return mcp


def make_everything_fastmcp_app():
    """Create a comprehensive FastMCP server with SSE transport."""
    from starlette.applications import Starlette

    mcp = make_everything_fastmcp()
    # Create the SSE app
    app: Starlette = mcp.sse_app()
    return mcp, app


def make_fastmcp_streamable_http_app():
    """Create a FastMCP server with StreamableHTTP transport."""
    from starlette.applications import Starlette

    mcp = FastMCP(name="NoAuthServer")

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()

    return mcp, app


def make_everything_fastmcp_streamable_http_app():
    """Create a comprehensive FastMCP server with StreamableHTTP transport."""
    from starlette.applications import Starlette

    # Create a new instance with different name for HTTP transport
    mcp = make_everything_fastmcp()
    # We can't change the name after creation, so we'll use the same name
    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()
    return mcp, app


def make_fastmcp_stateless_http_app():
    """Create a FastMCP server with stateless StreamableHTTP transport."""
    from starlette.applications import Starlette

    mcp = FastMCP(name="StatelessServer", stateless_http=True)

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()

    return mcp, app


def run_server(server_port: int) -> None:
    """Run the server."""
    _, app = make_fastmcp_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting server on port {server_port}")
    server.run()


def run_everything_legacy_sse_http_server(server_port: int) -> None:
    """Run the comprehensive server with all features."""
    _, app = make_everything_fastmcp_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting comprehensive server on port {server_port}")
    server.run()


def run_streamable_http_server(server_port: int) -> None:
    """Run the StreamableHTTP server."""
    _, app = make_fastmcp_streamable_http_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting StreamableHTTP server on port {server_port}")
    server.run()


def run_everything_server(server_port: int) -> None:
    """Run the comprehensive StreamableHTTP server with all features."""
    _, app = make_everything_fastmcp_streamable_http_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting comprehensive StreamableHTTP server on port {server_port}")
    server.run()


def run_stateless_http_server(server_port: int) -> None:
    """Run the stateless StreamableHTTP server."""
    _, app = make_fastmcp_stateless_http_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting stateless StreamableHTTP server on port {server_port}")
    server.run()


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    """Start the server in a separate process and clean up after the test."""
    proc = multiprocessing.Process(target=run_server, args=(server_port,), daemon=True)
    print("Starting server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for server to start")
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

    yield

    print("Killing server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Server process failed to terminate")


@pytest.fixture()
def streamable_http_server(http_server_port: int) -> Generator[None, None, None]:
    """Start the StreamableHTTP server in a separate process."""
    proc = multiprocessing.Process(
        target=run_streamable_http_server, args=(http_server_port,), daemon=True
    )
    print("Starting StreamableHTTP server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for StreamableHTTP server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", http_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(
            f"StreamableHTTP server failed to start after {max_attempts} attempts"
        )

    yield

    print("Killing StreamableHTTP server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("StreamableHTTP server process failed to terminate")


@pytest.fixture()
def stateless_http_server(
    stateless_http_server_port: int,
) -> Generator[None, None, None]:
    """Start the stateless StreamableHTTP server in a separate process."""
    proc = multiprocessing.Process(
        target=run_stateless_http_server,
        args=(stateless_http_server_port,),
        daemon=True,
    )
    print("Starting stateless StreamableHTTP server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for stateless StreamableHTTP server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", stateless_http_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(
            f"Stateless server failed to start after {max_attempts} attempts"
        )

    yield

    print("Killing stateless StreamableHTTP server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Stateless StreamableHTTP server process failed to terminate")


@pytest.mark.anyio
async def test_fastmcp_without_auth(server: None, server_url: str) -> None:
    """Test that FastMCP works when auth settings are not provided."""
    # Connect to the server
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "NoAuthServer"

            # Test that we can call tools without authentication
            tool_result = await session.call_tool("echo", {"message": "hello"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "Echo: hello"


@pytest.mark.anyio
async def test_fastmcp_streamable_http(
    streamable_http_server: None, http_server_url: str
) -> None:
    """Test that FastMCP works with StreamableHTTP transport."""
    # Connect to the server using StreamableHTTP
    async with streamablehttp_client(http_server_url + "/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        # Create a session using the client streams
        async with ClientSession(read_stream, write_stream) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "NoAuthServer"

            # Test that we can call tools without authentication
            tool_result = await session.call_tool("echo", {"message": "hello"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "Echo: hello"


@pytest.mark.anyio
async def test_fastmcp_stateless_streamable_http(
    stateless_http_server: None, stateless_http_server_url: str
) -> None:
    """Test that FastMCP works with stateless StreamableHTTP transport."""
    # Connect to the server using StreamableHTTP
    async with streamablehttp_client(stateless_http_server_url + "/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "StatelessServer"
            tool_result = await session.call_tool("echo", {"message": "hello"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "Echo: hello"

            for i in range(3):
                tool_result = await session.call_tool("echo", {"message": f"test_{i}"})
                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                assert tool_result.content[0].text == f"Echo: test_{i}"


@pytest.fixture
def everything_server_port() -> int:
    """Get a free port for testing the comprehensive server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def everything_server_url(everything_server_port: int) -> str:
    """Get the comprehensive server URL for testing."""
    return f"http://127.0.0.1:{everything_server_port}"


@pytest.fixture
def everything_http_server_port() -> int:
    """Get a free port for testing the comprehensive StreamableHTTP server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def everything_http_server_url(everything_http_server_port: int) -> str:
    """Get the comprehensive StreamableHTTP server URL for testing."""
    return f"http://127.0.0.1:{everything_http_server_port}"


@pytest.fixture()
def everything_server(everything_server_port: int) -> Generator[None, None, None]:
    """Start the comprehensive server in a separate process and clean up after."""
    proc = multiprocessing.Process(
        target=run_everything_legacy_sse_http_server,
        args=(everything_server_port,),
        daemon=True,
    )
    print("Starting comprehensive server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for comprehensive server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", everything_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(
            f"Comprehensive server failed to start after {max_attempts} attempts"
        )

    yield

    print("Killing comprehensive server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Comprehensive server process failed to terminate")


@pytest.fixture()
def everything_streamable_http_server(
    everything_http_server_port: int,
) -> Generator[None, None, None]:
    """Start the comprehensive StreamableHTTP server in a separate process."""
    proc = multiprocessing.Process(
        target=run_everything_server,
        args=(everything_http_server_port,),
        daemon=True,
    )
    print("Starting comprehensive StreamableHTTP server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for comprehensive StreamableHTTP server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", everything_http_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(
            f"Comprehensive StreamableHTTP server failed to start after "
            f"{max_attempts} attempts"
        )

    yield

    print("Killing comprehensive StreamableHTTP server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Comprehensive StreamableHTTP server process failed to terminate")


class NotificationCollector:
    def __init__(self):
        self.progress_notifications: list = []
        self.log_messages: list = []
        self.resource_notifications: list = []
        self.tool_notifications: list = []

    async def handle_progress(self, params) -> None:
        self.progress_notifications.append(params)

    async def handle_log(self, params) -> None:
        self.log_messages.append(params)

    async def handle_resource_list_changed(self, params) -> None:
        self.resource_notifications.append(params)

    async def handle_tool_list_changed(self, params) -> None:
        self.tool_notifications.append(params)

    async def handle_generic_notification(self, message) -> None:
        # Check if this is a ServerNotification
        if isinstance(message, types.ServerNotification):
            # Check the specific notification type
            if isinstance(message.root, types.ProgressNotification):
                await self.handle_progress(message.root.params)
            elif isinstance(message.root, types.LoggingMessageNotification):
                await self.handle_log(message.root.params)
            elif isinstance(message.root, types.ResourceListChangedNotification):
                await self.handle_resource_list_changed(message.root.params)
            elif isinstance(message.root, types.ToolListChangedNotification):
                await self.handle_tool_list_changed(message.root.params)


async def call_all_mcp_features(
    session: ClientSession, collector: NotificationCollector
) -> None:
    """
    Test all MCP features using the provided session.

    Args:
        session: The MCP client session to test with
        collector: Notification collector for capturing server notifications
    """
    # Test initialization
    result = await session.initialize()
    assert isinstance(result, InitializeResult)
    assert result.serverInfo.name == "EverythingServer"

    # Check server features are reported
    assert result.capabilities.prompts is not None
    assert result.capabilities.resources is not None
    assert result.capabilities.tools is not None
    # Note: logging capability may be None if no tools use context logging

    # Test tools
    # 1. Simple echo tool
    tool_result = await session.call_tool("echo", {"message": "hello"})
    assert len(tool_result.content) == 1
    assert isinstance(tool_result.content[0], TextContent)
    assert tool_result.content[0].text == "Echo: hello"

    # 2. Tool with context (logging and progress)
    # Test progress callback functionality
    progress_updates = []

    async def progress_callback(
        progress: float, total: float | None, message: str | None
    ) -> None:
        """Collect progress updates for testing (async version)."""
        progress_updates.append((progress, total, message))
        print(f"Progress: {progress}/{total} - {message}")

    test_message = "test"
    steps = 3
    params = {
        "message": test_message,
        "steps": steps,
    }
    tool_result = await session.call_tool(
        "tool_with_progress",
        params,
        progress_callback=progress_callback,
    )
    assert len(tool_result.content) == 1
    assert isinstance(tool_result.content[0], TextContent)
    assert f"Processed '{test_message}' in {steps} steps" in tool_result.content[0].text

    # Verify progress callback was called
    assert len(progress_updates) == steps
    for i, (progress, total, message) in enumerate(progress_updates):
        expected_progress = (i + 1) / steps
        assert abs(progress - expected_progress) < 0.01
        assert total == 1.0
        assert message is not None
        assert f"step {i + 1} of {steps}" in message

    # Verify we received log messages from the tool
    # Note: Progress notifications require special handling in the MCP client
    # that's not implemented by default, so we focus on testing logging
    assert len(collector.log_messages) > 0

    # 3. Test sampling tool
    prompt = "What is the meaning of life?"
    sampling_result = await session.call_tool("sampling_tool", {"prompt": prompt})
    assert len(sampling_result.content) == 1
    assert isinstance(sampling_result.content[0], TextContent)
    assert "Sampling result:" in sampling_result.content[0].text
    assert "This is a simulated LLM response" in sampling_result.content[0].text

    # Verify we received log messages from the sampling tool
    assert len(collector.log_messages) > 0
    assert any(
        "Requesting sampling for prompt" in msg.data for msg in collector.log_messages
    )
    assert any(
        "Received sampling result from model" in msg.data
        for msg in collector.log_messages
    )

    # 4. Test notification tool
    notification_message = "test_notifications"
    notification_result = await session.call_tool(
        "notification_tool", {"message": notification_message}
    )
    assert len(notification_result.content) == 1
    assert isinstance(notification_result.content[0], TextContent)
    assert "Sent notifications and logs" in notification_result.content[0].text

    # Verify we received various notification types
    assert len(collector.log_messages) > 3  # Should have logs from both tools
    assert len(collector.resource_notifications) > 0
    assert len(collector.tool_notifications) > 0

    # Check that we got different log levels
    log_levels = [msg.level for msg in collector.log_messages]
    assert "debug" in log_levels
    assert "info" in log_levels
    assert "warning" in log_levels

    # Test resources
    # 1. Static resource
    resources = await session.list_resources()
    # Try using string comparison since AnyUrl might not match directly
    static_resource = next(
        (r for r in resources.resources if str(r.uri) == "resource://static/info"),
        None,
    )
    assert static_resource is not None
    assert static_resource.name == "Static Info"

    static_content = await session.read_resource(AnyUrl("resource://static/info"))
    assert isinstance(static_content, ReadResourceResult)
    assert len(static_content.contents) == 1
    assert isinstance(static_content.contents[0], TextResourceContents)
    assert static_content.contents[0].text == "This is static resource content"

    # 2. Dynamic resource
    resource_category = "test"
    dynamic_content = await session.read_resource(
        AnyUrl(f"resource://dynamic/{resource_category}")
    )
    assert isinstance(dynamic_content, ReadResourceResult)
    assert len(dynamic_content.contents) == 1
    assert isinstance(dynamic_content.contents[0], TextResourceContents)
    assert (
        f"Dynamic resource content for category: {resource_category}"
        in dynamic_content.contents[0].text
    )

    # 3. Template resource
    resource_id = "456"
    template_content = await session.read_resource(
        AnyUrl(f"resource://template/{resource_id}/data")
    )
    assert isinstance(template_content, ReadResourceResult)
    assert len(template_content.contents) == 1
    assert isinstance(template_content.contents[0], TextResourceContents)
    assert (
        f"Template resource data for ID: {resource_id}"
        in template_content.contents[0].text
    )

    # Test prompts
    # 1. Simple prompt
    prompts = await session.list_prompts()
    simple_prompt = next(
        (p for p in prompts.prompts if p.name == "simple_prompt"), None
    )
    assert simple_prompt is not None

    prompt_topic = "AI"
    prompt_result = await session.get_prompt("simple_prompt", {"topic": prompt_topic})
    assert isinstance(prompt_result, GetPromptResult)
    assert len(prompt_result.messages) >= 1
    # The actual message structure depends on the prompt implementation

    # 2. Complex prompt
    complex_prompt = next(
        (p for p in prompts.prompts if p.name == "complex_prompt"), None
    )
    assert complex_prompt is not None

    query = "What is AI?"
    context = "technical"
    complex_result = await session.get_prompt(
        "complex_prompt", {"user_query": query, "context": context}
    )
    assert isinstance(complex_result, GetPromptResult)
    assert len(complex_result.messages) >= 1


async def sampling_callback(
    context: RequestContext[ClientSession, None],
    params: CreateMessageRequestParams,
) -> CreateMessageResult:
    # Simulate LLM response based on the input
    if params.messages and isinstance(params.messages[0].content, TextContent):
        input_text = params.messages[0].content.text
    else:
        input_text = "No input"
    response_text = f"This is a simulated LLM response to: {input_text}"

    model_name = "test-llm-model"
    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text=response_text),
        model=model_name,
        stopReason="endTurn",
    )


@pytest.mark.anyio
async def test_fastmcp_all_features_sse(
    everything_server: None, everything_server_url: str
) -> None:
    """Test all MCP features work correctly with SSE transport."""

    # Create notification collector
    collector = NotificationCollector()

    # Create a sampling callback that simulates an LLM

    # Connect to the server with callbacks
    async with sse_client(everything_server_url + "/sse") as streams:
        # Set up message handler to capture notifications
        async def message_handler(message):
            print(f"Received message: {message}")
            await collector.handle_generic_notification(message)
            if isinstance(message, Exception):
                raise message

        async with ClientSession(
            *streams,
            sampling_callback=sampling_callback,
            message_handler=message_handler,
        ) as session:
            # Run the common test suite
            await call_all_mcp_features(session, collector)


@pytest.mark.anyio
async def test_fastmcp_all_features_streamable_http(
    everything_streamable_http_server: None, everything_http_server_url: str
) -> None:
    """Test all MCP features work correctly with StreamableHTTP transport."""

    # Create notification collector
    collector = NotificationCollector()

    # Connect to the server using StreamableHTTP
    async with streamablehttp_client(everything_http_server_url + "/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        # Set up message handler to capture notifications
        async def message_handler(message):
            print(f"Received message: {message}")
            await collector.handle_generic_notification(message)
            if isinstance(message, Exception):
                raise message

        async with ClientSession(
            read_stream,
            write_stream,
            sampling_callback=sampling_callback,
            message_handler=message_handler,
        ) as session:
            # Run the common test suite with HTTP-specific test suffix
            await call_all_mcp_features(session, collector)
