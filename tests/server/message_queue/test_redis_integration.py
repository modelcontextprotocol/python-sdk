import multiprocessing
import socket
import time
from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import anyio
import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

SERVER_NAME = "test_server_for_redis_integration"

# Set up fakeredis for testing
try:
    from fakeredis import aioredis as fake_redis
except ImportError:
    pytest.skip(
        "fakeredis is required for testing Redis functionality", allow_module_level=True
    )


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


# Test server implementation
class RedisTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="test_tool",
                    description="A test tool",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict) -> list[TextContent]:
            return [TextContent(type="text", text=f"Called {name}")]


def make_redis_server_app() -> Starlette:
    """Create test Starlette app with SSE transport and Redis message dispatch"""
    # Create a mock Redis instance
    mock_redis = fake_redis.FakeRedis()
    
    # Patch the redis module within RedisMessageDispatch
    with patch("mcp.server.message_queue.redis.redis", mock_redis):
        from mcp.server.message_queue.redis import RedisMessageDispatch
        
        # Create Redis message dispatch with mock redis
        message_dispatch = RedisMessageDispatch("redis://localhost:6379/0")
        
        # Create SSE transport with Redis message dispatch
        sse = SseServerTransport("/messages/", message_dispatch=message_dispatch)
        server = RedisTestServer()

        async def handle_sse(request: Request) -> None:
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1], server.create_initialization_options()
                )

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )

        return app


def run_redis_server(server_port: int) -> None:
    app = make_redis_server_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    server.run()

    # Give server time to start
    while not server.started:
        time.sleep(0.5)


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(
        target=run_redis_server, kwargs={"server_port": server_port}, daemon=True
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

    yield

    # Signal the server to stop
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("server process failed to terminate")


@pytest.fixture()
async def http_client(server, server_url) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create test client"""
    async with httpx.AsyncClient(base_url=server_url) as client:
        yield client


@pytest.mark.anyio
async def test_redis_integration_basic_connection(server: None, server_url: str) -> None:
    """Test that a basic SSE connection works with Redis message dispatch"""
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert result.serverInfo.name == SERVER_NAME


@pytest.mark.anyio
async def test_redis_integration_tool_call(server: None, server_url: str) -> None:
    """Test that a tool call works with Redis message dispatch"""
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Initialize session
            await session.initialize()
            
            # Call a tool
            result = await session.call_tool("test_tool", {})
            assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_redis_integration_session_lifecycle() -> None:
    """Test that sessions are properly added to and removed from Redis using direct Redis access"""
    # Create a fresh Redis instance with decode_responses=True to get str instead of bytes
    mock_redis = fake_redis.FakeRedis(decode_responses=True)
    active_sessions_key = "mcp:pubsub:active_sessions"
    
    # Mock Redis in RedisMessageDispatch
    with patch("mcp.server.message_queue.redis.redis.from_url", return_value=mock_redis):
        from mcp.server.message_queue.redis import RedisMessageDispatch
        
        # Create Redis message dispatch with our specific mock redis instance
        message_dispatch = RedisMessageDispatch("redis://localhost:6379/0")
        
        # Create a mock callback
        async def mock_callback(message):
            pass
        
        # Test session subscription and unsubscription
        from uuid import uuid4
        session_id = uuid4()
        
        # Subscribe to a session
        async with message_dispatch.subscribe(session_id, mock_callback):
            # Give a moment for the session to be added
            await anyio.sleep(0.05)
            
            # Check that session was added to Redis
            active_sessions = await mock_redis.smembers(active_sessions_key)
            assert len(active_sessions) == 1
            assert list(active_sessions)[0] == session_id.hex
            
            # Verify session exists
            assert await message_dispatch.session_exists(session_id)
        
        # Give a moment for cleanup
        await anyio.sleep(0.05)
        
        # After context exit, verify the session was removed
        final_sessions = await mock_redis.smembers(active_sessions_key)
        assert len(final_sessions) == 0
        assert not await message_dispatch.session_exists(session_id)


@pytest.mark.anyio
async def test_redis_integration_message_publishing_direct() -> None:
    """Test message publishing through Redis channels using direct Redis access"""
    # Create a fresh Redis instance with decode_responses=True to get str instead of bytes
    mock_redis = fake_redis.FakeRedis(decode_responses=True)
    
    # Mock Redis in RedisMessageDispatch
    with patch("mcp.server.message_queue.redis.redis.from_url", return_value=mock_redis):
        from mcp.server.message_queue.redis import RedisMessageDispatch
        from mcp.types import JSONRPCMessage, JSONRPCRequest
        
        # Create Redis message dispatch with our specific mock redis instance
        message_dispatch = RedisMessageDispatch("redis://localhost:6379/0")
        
        # Messages received through the callback
        messages_received = []
        
        async def message_callback(message):
            messages_received.append(message)
        
        # Use a UUID for session ID
        from uuid import uuid4
        session_id = uuid4()
        
        # Subscribe to the session
        async with message_dispatch.subscribe(session_id, message_callback):
            # Give a moment for subscription to be fully set up and start listener task
            await anyio.sleep(0.05)
            
            # Create a test message
            test_message = JSONRPCMessage(
                root=JSONRPCRequest(jsonrpc="2.0", id=1, method="test_method", params={})
            )
            
            # Publish the message
            success = await message_dispatch.publish_message(session_id, test_message)
            assert success
            
            # Give some time for the message to be processed
            # Use a shorter sleep since we're in controlled test environment
            await anyio.sleep(0.1)
            
            # Verify that the message was received
            assert len(messages_received) > 0, "No messages were received through the callback"
            received_message = messages_received[0]
            assert isinstance(received_message, JSONRPCMessage)
            assert received_message.root.method == "test_method"
            assert received_message.root.id == 1