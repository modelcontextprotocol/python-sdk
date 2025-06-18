"""
Integration tests for FastMCP server functionality.

These tests validate the proper functioning of FastMCP in various configurations,
including with and without authentication.
"""

import json
import multiprocessing
import socket
import time
from collections.abc import Generator
from typing import Any

import pytest
import uvicorn
from pydantic import AnyUrl, BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.context import RequestContext
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitResult,
    GetPromptResult,
    InitializeResult,
    LoggingMessageNotification,
    ProgressNotification,
    PromptReference,
    ReadResourceResult,
    ResourceLink,
    ResourceListChangedNotification,
    ResourceTemplateReference,
    SamplingMessage,
    ServerNotification,
    TextContent,
    TextResourceContents,
    ToolListChangedNotification,
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
    transport_security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    mcp = FastMCP(name="NoAuthServer", transport_security=transport_security)

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Add a tool that uses elicitation
    @mcp.tool(description="A tool that uses elicitation")
    async def ask_user(prompt: str, ctx: Context) -> str:
        class AnswerSchema(BaseModel):
            answer: str = Field(description="The user's answer to the question")

        result = await ctx.elicit(message=f"Tool wants to ask: {prompt}", schema=AnswerSchema)

        if result.action == "accept" and result.data:
            return f"User answered: {result.data.answer}"
        else:
            # Handle cancellation or decline
            return f"User cancelled or declined: {result.action}"

    # Create the SSE app
    app = mcp.sse_app()

    return mcp, app


def make_everything_fastmcp() -> FastMCP:
    """Create a FastMCP server with all features enabled for testing."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    mcp = FastMCP(name="EverythingServer", transport_security=transport_security)

    # Tool with context for logging and progress
    @mcp.tool(description="A tool that demonstrates logging and progress", title="Progress Tool")
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
    @mcp.tool(description="A simple echo tool", title="Echo Tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Tool that returns ResourceLinks
    @mcp.tool(description="Lists files and returns resource links", title="List Files Tool")
    def list_files() -> list[ResourceLink]:
        """Returns a list of resource links for files matching the pattern."""

        # Mock some file resources for testing
        file_resources = [
            {
                "type": "resource_link",
                "uri": "file:///project/README.md",
                "name": "README.md",
                "mimeType": "text/markdown",
            }
        ]

        result: list[ResourceLink] = [ResourceLink.model_validate(file_json) for file_json in file_resources]

        return result

    # Tool with sampling capability
    @mcp.tool(description="A tool that uses sampling to generate content", title="Sampling Tool")
    async def sampling_tool(prompt: str, ctx: Context) -> str:
        await ctx.info(f"Requesting sampling for prompt: {prompt}")

        # Request sampling from the client
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
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
    @mcp.tool(description="A tool that demonstrates notifications and logging", title="Notification Tool")
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
        title="Static Information",
        description="Static information resource",
        fn=get_static_info,
    )
    mcp.add_resource(static_resource)

    # Resource - dynamic function
    @mcp.resource("resource://dynamic/{category}", title="Dynamic Resource")
    def dynamic_resource(category: str) -> str:
        return f"Dynamic resource content for category: {category}"

    # Resource template
    @mcp.resource("resource://template/{id}/data", title="Template Resource")
    def template_resource(id: str) -> str:
        return f"Template resource data for ID: {id}"

    # Prompt - simple
    @mcp.prompt(description="A simple prompt", title="Simple Prompt")
    def simple_prompt(topic: str) -> str:
        return f"Tell me about {topic}"

    # Prompt - complex with multiple messages
    @mcp.prompt(description="Complex prompt with context", title="Complex Prompt")
    def complex_prompt(user_query: str, context: str = "general") -> str:
        # For simplicity, return a single string that incorporates the context
        # Since FastMCP doesn't support system messages in the same way
        return f"Context: {context}. Query: {user_query}"

    # Resource template with completion support
    @mcp.resource("github://repos/{owner}/{repo}", title="GitHub Repository")
    def github_repo_resource(owner: str, repo: str) -> str:
        return f"Repository: {owner}/{repo}"

    # Add completion handler for the server
    @mcp.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        # Handle GitHub repository completion
        if isinstance(ref, ResourceTemplateReference):
            if ref.uri == "github://repos/{owner}/{repo}" and argument.name == "repo":
                if context and context.arguments and context.arguments.get("owner") == "modelcontextprotocol":
                    # Return repos for modelcontextprotocol org
                    return Completion(values=["python-sdk", "typescript-sdk", "specification"], total=3, hasMore=False)
                elif context and context.arguments and context.arguments.get("owner") == "test-org":
                    # Return repos for test-org
                    return Completion(values=["test-repo1", "test-repo2"], total=2, hasMore=False)

        # Handle prompt completions
        if isinstance(ref, PromptReference):
            if ref.name == "complex_prompt" and argument.name == "context":
                # Complete context values
                contexts = ["general", "technical", "business", "academic"]
                return Completion(
                    values=[c for c in contexts if c.startswith(argument.value)], total=None, hasMore=False
                )

        # Default: no completion available
        return Completion(values=[], total=0, hasMore=False)

    # Tool that echoes request headers from context
    @mcp.tool(description="Echo request headers from context", title="Echo Headers")
    def echo_headers(ctx: Context[Any, Any, Request]) -> str:
        """Returns the request headers as JSON."""
        headers_info = {}
        if ctx.request_context.request:
            # Now the type system knows request is a Starlette Request object
            headers_info = dict(ctx.request_context.request.headers)
        return json.dumps(headers_info)

    # Tool that returns full request context
    @mcp.tool(description="Echo request context with custom data", title="Echo Context")
    def echo_context(custom_request_id: str, ctx: Context[Any, Any, Request]) -> str:
        """Returns request context including headers and custom data."""
        context_data = {
            "custom_request_id": custom_request_id,
            "headers": {},
            "method": None,
            "path": None,
        }
        if ctx.request_context.request:
            request = ctx.request_context.request
            context_data["headers"] = dict(request.headers)
            context_data["method"] = request.method
            context_data["path"] = request.url.path
        return json.dumps(context_data)

    # Restaurant booking tool with elicitation
    @mcp.tool(description="Book a table at a restaurant with elicitation", title="Restaurant Booking")
    async def book_restaurant(
        date: str,
        time: str,
        party_size: int,
        ctx: Context,
    ) -> str:
        """Book a table - uses elicitation if requested date is unavailable."""

        class AlternativeDateSchema(BaseModel):
            checkAlternative: bool = Field(description="Would you like to try another date?")
            alternativeDate: str = Field(
                default="2024-12-26",
                description="What date would you prefer? (YYYY-MM-DD)",
            )

        # For testing: assume dates starting with "2024-12-25" are unavailable
        if date.startswith("2024-12-25"):
            # Use elicitation to ask about alternatives
            result = await ctx.elicit(
                message=(
                    f"No tables available for {party_size} people on {date} "
                    f"at {time}. Would you like to check another date?"
                ),
                schema=AlternativeDateSchema,
            )

            if result.action == "accept" and result.data:
                if result.data.checkAlternative:
                    alt_date = result.data.alternativeDate
                    return f"✅ Booked table for {party_size} on {alt_date} at {time}"
                else:
                    return "❌ No booking made"
            elif result.action in ("decline", "cancel"):
                return "❌ Booking cancelled"
            else:
                # Handle case where action is "accept" but data is None
                return "❌ No booking data received"
        else:
            # Available - book directly
            return f"✅ Booked table for {party_size} on {date} at {time}"

    return mcp


def make_everything_fastmcp_app():
    """Create a comprehensive FastMCP server with SSE transport."""
    mcp = make_everything_fastmcp()
    # Create the SSE app
    app = mcp.sse_app()
    return mcp, app


def make_fastmcp_streamable_http_app():
    """Create a FastMCP server with StreamableHTTP transport."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    mcp = FastMCP(name="NoAuthServer", transport_security=transport_security)

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()

    return mcp, app


def make_everything_fastmcp_streamable_http_app():
    """Create a comprehensive FastMCP server with StreamableHTTP transport."""
    # Create a new instance with different name for HTTP transport
    mcp = make_everything_fastmcp()
    # We can't change the name after creation, so we'll use the same name
    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()
    return mcp, app


def make_fastmcp_stateless_http_app():
    """Create a FastMCP server with stateless StreamableHTTP transport."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    mcp = FastMCP(name="StatelessServer", stateless_http=True, transport_security=transport_security)

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
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"Starting server on port {server_port}")
    server.run()


def run_everything_legacy_sse_http_server(server_port: int) -> None:
    """Run the comprehensive server with all features."""
    _, app = make_everything_fastmcp_app()
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"Starting comprehensive server on port {server_port}")
    server.run()


def run_streamable_http_server(server_port: int) -> None:
    """Run the StreamableHTTP server."""
    _, app = make_fastmcp_streamable_http_app()
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"Starting StreamableHTTP server on port {server_port}")
    server.run()


def run_everything_server(server_port: int) -> None:
    """Run the comprehensive StreamableHTTP server with all features."""
    _, app = make_everything_fastmcp_streamable_http_app()
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"Starting comprehensive StreamableHTTP server on port {server_port}")
    server.run()


def run_stateless_http_server(server_port: int) -> None:
    """Run the stateless StreamableHTTP server."""
    _, app = make_fastmcp_stateless_http_app()
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
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
    proc = multiprocessing.Process(target=run_streamable_http_server, args=(http_server_port,), daemon=True)
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
        raise RuntimeError(f"StreamableHTTP server failed to start after {max_attempts} attempts")

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
        raise RuntimeError(f"Stateless server failed to start after {max_attempts} attempts")

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
async def test_fastmcp_streamable_http(streamable_http_server: None, http_server_url: str) -> None:
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
async def test_fastmcp_stateless_streamable_http(stateless_http_server: None, stateless_http_server_url: str) -> None:
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
        raise RuntimeError(f"Comprehensive server failed to start after {max_attempts} attempts")

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
        raise RuntimeError(f"Comprehensive StreamableHTTP server failed to start after " f"{max_attempts} attempts")

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
        if isinstance(message, ServerNotification):
            # Check the specific notification type
            if isinstance(message.root, ProgressNotification):
                await self.handle_progress(message.root.params)
            elif isinstance(message.root, LoggingMessageNotification):
                await self.handle_log(message.root.params)
            elif isinstance(message.root, ResourceListChangedNotification):
                await self.handle_resource_list_changed(message.root.params)
            elif isinstance(message.root, ToolListChangedNotification):
                await self.handle_tool_list_changed(message.root.params)


async def create_test_elicitation_callback(context, params):
    """Shared elicitation callback for tests.

    Handles elicitation requests for restaurant booking tests.
    """
    # For restaurant booking test
    if "No tables available" in params.message:
        return ElicitResult(
            action="accept",
            content={"checkAlternative": True, "alternativeDate": "2024-12-26"},
        )
    else:
        # Default response
        return ElicitResult(action="decline")


async def call_all_mcp_features(session: ClientSession, collector: NotificationCollector) -> None:
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

    # 2. Test tool that returns ResourceLinks
    list_files_result = await session.call_tool("list_files")
    assert len(list_files_result.content) == 1

    # Rest should be ResourceLinks
    content = list_files_result.content[0]
    assert isinstance(content, ResourceLink)
    assert str(content.uri).startswith("file:///")
    assert content.name is not None
    assert content.mimeType is not None

    # Test progress callback functionality
    progress_updates = []

    async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
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
    assert any("Requesting sampling for prompt" in msg.data for msg in collector.log_messages)
    assert any("Received sampling result from model" in msg.data for msg in collector.log_messages)

    # 4. Test notification tool
    notification_message = "test_notifications"
    notification_result = await session.call_tool("notification_tool", {"message": notification_message})
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

    # 5. Test elicitation tool
    # Test restaurant booking with unavailable date (triggers elicitation)
    booking_result = await session.call_tool(
        "book_restaurant",
        {
            "date": "2024-12-25",  # Unavailable date to trigger elicitation
            "time": "19:00",
            "party_size": 4,
        },
    )
    assert len(booking_result.content) == 1
    assert isinstance(booking_result.content[0], TextContent)
    # Should have booked the alternative date from elicitation callback
    assert "✅ Booked table for 4 on 2024-12-26" in booking_result.content[0].text

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
    dynamic_content = await session.read_resource(AnyUrl(f"resource://dynamic/{resource_category}"))
    assert isinstance(dynamic_content, ReadResourceResult)
    assert len(dynamic_content.contents) == 1
    assert isinstance(dynamic_content.contents[0], TextResourceContents)
    assert f"Dynamic resource content for category: {resource_category}" in dynamic_content.contents[0].text

    # 3. Template resource
    resource_id = "456"
    template_content = await session.read_resource(AnyUrl(f"resource://template/{resource_id}/data"))
    assert isinstance(template_content, ReadResourceResult)
    assert len(template_content.contents) == 1
    assert isinstance(template_content.contents[0], TextResourceContents)
    assert f"Template resource data for ID: {resource_id}" in template_content.contents[0].text

    # Test prompts
    # 1. Simple prompt
    prompts = await session.list_prompts()
    simple_prompt = next((p for p in prompts.prompts if p.name == "simple_prompt"), None)
    assert simple_prompt is not None

    prompt_topic = "AI"
    prompt_result = await session.get_prompt("simple_prompt", {"topic": prompt_topic})
    assert isinstance(prompt_result, GetPromptResult)
    assert len(prompt_result.messages) >= 1
    # The actual message structure depends on the prompt implementation

    # 2. Complex prompt
    complex_prompt = next((p for p in prompts.prompts if p.name == "complex_prompt"), None)
    assert complex_prompt is not None

    query = "What is AI?"
    context = "technical"
    complex_result = await session.get_prompt("complex_prompt", {"user_query": query, "context": context})
    assert isinstance(complex_result, GetPromptResult)
    assert len(complex_result.messages) >= 1

    # Test request context propagation (only works when headers are available)

    headers_result = await session.call_tool("echo_headers", {})
    assert len(headers_result.content) == 1
    assert isinstance(headers_result.content[0], TextContent)

    # If we got headers, verify they exist
    headers_data = json.loads(headers_result.content[0].text)
    # The headers depend on the transport and test setup
    print(f"Received headers: {headers_data}")

    # Test 6: Call tool that returns full context
    context_result = await session.call_tool("echo_context", {"custom_request_id": "test-123"})
    assert len(context_result.content) == 1
    assert isinstance(context_result.content[0], TextContent)

    context_data = json.loads(context_result.content[0].text)
    assert context_data["custom_request_id"] == "test-123"
    # The method should be POST for most transports
    if context_data["method"]:
        assert context_data["method"] == "POST"

    # Test completion functionality
    # 1. Test resource template completion with context
    repo_result = await session.complete(
        ref=ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
        argument={"name": "repo", "value": ""},
        context_arguments={"owner": "modelcontextprotocol"},
    )
    assert repo_result.completion.values == ["python-sdk", "typescript-sdk", "specification"]
    assert repo_result.completion.total == 3
    assert repo_result.completion.hasMore is False

    # 2. Test with different context
    repo_result2 = await session.complete(
        ref=ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
        argument={"name": "repo", "value": ""},
        context_arguments={"owner": "test-org"},
    )
    assert repo_result2.completion.values == ["test-repo1", "test-repo2"]
    assert repo_result2.completion.total == 2

    # 3. Test prompt argument completion
    context_result = await session.complete(
        ref=PromptReference(type="ref/prompt", name="complex_prompt"),
        argument={"name": "context", "value": "tech"},
    )
    assert "technical" in context_result.completion.values

    # 4. Test completion without context (should return empty)
    no_context_result = await session.complete(
        ref=ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
        argument={"name": "repo", "value": "test"},
    )
    assert no_context_result.completion.values == []
    assert no_context_result.completion.total == 0


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
async def test_fastmcp_all_features_sse(everything_server: None, everything_server_url: str) -> None:
    """Test all MCP features work correctly with SSE transport."""

    # Create notification collector
    collector = NotificationCollector()

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
            elicitation_callback=create_test_elicitation_callback,
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
            elicitation_callback=create_test_elicitation_callback,
            message_handler=message_handler,
        ) as session:
            # Run the common test suite with HTTP-specific test suffix
            await call_all_mcp_features(session, collector)


@pytest.mark.anyio
async def test_elicitation_feature(server: None, server_url: str) -> None:
    """Test the elicitation feature."""

    # Create a custom handler for elicitation requests
    async def elicitation_callback(context, params):
        # Verify the elicitation parameters
        if params.message == "Tool wants to ask: What is your name?":
            return ElicitResult(content={"answer": "Test User"}, action="accept")
        else:
            raise ValueError("Unexpected elicitation message")

    # Connect to the server with our custom elicitation handler
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams, elicitation_callback=elicitation_callback) as session:
            # First initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "NoAuthServer"

            # Call the tool that uses elicitation
            tool_result = await session.call_tool("ask_user", {"prompt": "What is your name?"})
            # Verify the result
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            # # The test should only succeed with the successful elicitation response
            assert tool_result.content[0].text == "User answered: Test User"


@pytest.mark.anyio
async def test_title_precedence(everything_server: None, everything_server_url: str) -> None:
    """Test that titles are properly returned for tools, resources, and prompts."""
    from mcp.shared.metadata_utils import get_display_name

    async with sse_client(everything_server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            # Test tools have titles
            tools_result = await session.list_tools()
            assert tools_result.tools

            # Check specific tools have titles
            tool_names_to_titles = {
                "tool_with_progress": "Progress Tool",
                "echo": "Echo Tool",
                "sampling_tool": "Sampling Tool",
                "notification_tool": "Notification Tool",
                "echo_headers": "Echo Headers",
                "echo_context": "Echo Context",
                "book_restaurant": "Restaurant Booking",
            }

            for tool in tools_result.tools:
                if tool.name in tool_names_to_titles:
                    assert tool.title == tool_names_to_titles[tool.name]
                    # Test get_display_name utility
                    assert get_display_name(tool) == tool_names_to_titles[tool.name]

            # Test resources have titles
            resources_result = await session.list_resources()
            assert resources_result.resources

            # Check specific resources have titles
            static_resource = next((r for r in resources_result.resources if r.name == "Static Info"), None)
            assert static_resource is not None
            assert static_resource.title == "Static Information"
            assert get_display_name(static_resource) == "Static Information"

            # Test resource templates have titles
            resource_templates = await session.list_resource_templates()
            assert resource_templates.resourceTemplates

            # Check specific resource templates have titles
            template_uris_to_titles = {
                "resource://dynamic/{category}": "Dynamic Resource",
                "resource://template/{id}/data": "Template Resource",
                "github://repos/{owner}/{repo}": "GitHub Repository",
            }

            for template in resource_templates.resourceTemplates:
                if template.uriTemplate in template_uris_to_titles:
                    assert template.title == template_uris_to_titles[template.uriTemplate]
                    assert get_display_name(template) == template_uris_to_titles[template.uriTemplate]

            # Test prompts have titles
            prompts_result = await session.list_prompts()
            assert prompts_result.prompts

            # Check specific prompts have titles
            prompt_names_to_titles = {
                "simple_prompt": "Simple Prompt",
                "complex_prompt": "Complex Prompt",
            }

            for prompt in prompts_result.prompts:
                if prompt.name in prompt_names_to_titles:
                    assert prompt.title == prompt_names_to_titles[prompt.name]
                    assert get_display_name(prompt) == prompt_names_to_titles[prompt.name]
