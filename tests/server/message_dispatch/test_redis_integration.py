"""
Integration tests for Redis message dispatch functionality.

These tests validate Redis message dispatch by making actual HTTP calls and testing
that messages flow correctly through the Redis backend.

This version runs the server in a task instead of a separate process to allow
access to the fakeredis instance for verification of Redis keys.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
import pytest
import uvicorn
from sse_starlette.sse import AppStatus
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server import Server
from mcp.server.message_queue.redis import RedisMessageDispatch
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

SERVER_NAME = "test_server_for_redis_integration_v3"


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


class RedisTestServer(Server):
    """Test server with basic tool functionality."""

    def __init__(self):
        super().__init__(SERVER_NAME)

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="test_tool",
                    description="A test tool",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="echo_message",
                    description="Echo a message back",
                    inputSchema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                ),
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict) -> list[TextContent]:
            if name == "echo_message":
                message = args.get("message", "")
                return [TextContent(type="text", text=f"Echo: {message}")]
            return [TextContent(type="text", text=f"Called {name}")]


@pytest.fixture()
async def redis_server_and_app(message_dispatch: RedisMessageDispatch):
    """Create a mock Redis instance and Starlette app for testing."""

    # Create SSE transport with Redis message dispatch
    sse = SseServerTransport("/messages/", message_dispatch=message_dispatch)
    server = RedisTestServer()

    async def handle_sse(request: Request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )
        return Response()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        """Manage the lifecycle of the application."""
        try:
            yield
        finally:
            await message_dispatch.close()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
        lifespan=lifespan,
    )

    return app, message_dispatch, message_dispatch._redis


@pytest.fixture()
async def server_and_redis(redis_server_and_app, server_port: int):
    """Run the server in a task and return the Redis instance for inspection."""
    app, message_dispatch, mock_redis = redis_server_and_app

    # Create a server config
    config = uvicorn.Config(
        app=app, host="127.0.0.1", port=server_port, log_level="error"
    )
    server = uvicorn.Server(config=config)
    try:
        async with anyio.create_task_group() as tg:
            # Start server in background
            tg.start_soon(server.serve)

            # Wait for server to be ready
            max_attempts = 20
            attempt = 0
            while attempt < max_attempts:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.connect(("127.0.0.1", server_port))
                        break
                except ConnectionRefusedError:
                    await anyio.sleep(0.1)
                    attempt += 1
            else:
                raise RuntimeError(
                    f"Server failed to start after {max_attempts} attempts"
                )

            try:
                yield mock_redis, message_dispatch
            finally:
                server.should_exit = True
    finally:
        # These class variables are set top-level in starlette-sse
        # It isn't designed to be run multiple times in a single
        # Python process so we need to manually reset them.
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None


@pytest.fixture()
async def client_session(server_and_redis, server_url: str):
    """Create a client session for testing."""
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert result.serverInfo.name == SERVER_NAME
            yield session


@pytest.mark.anyio
async def test_redis_integration_key_verification(
    server_and_redis, client_session
) -> None:
    """Test that Redis keys are created correctly for sessions."""
    mock_redis, _ = server_and_redis

    all_keys = await mock_redis.keys("*")  # type: ignore

    assert len(all_keys) > 0

    session_key = None
    for key in all_keys:
        if key.startswith("mcp:pubsub:session_active:"):
            session_key = key
            break

    assert session_key is not None, f"No session key found. Keys: {all_keys}"

    ttl = await mock_redis.ttl(session_key)  # type: ignore
    assert ttl > 0, f"Session key should have TTL, got: {ttl}"


@pytest.mark.anyio
async def test_tool_calls(server_and_redis, client_session) -> None:
    """Test that messages are properly published through Redis."""
    mock_redis, _ = server_and_redis

    for i in range(3):
        tool_result = await client_session.call_tool(
            "echo_message", {"message": f"Test {i}"}
        )
        assert tool_result.content[0].text == f"Echo: Test {i}"  # type: ignore


@pytest.mark.anyio
async def test_session_cleanup(server_and_redis, server_url: str) -> None:
    """Test Redis key cleanup when sessions end."""
    mock_redis, _ = server_and_redis
    session_keys_seen = set()

    for i in range(3):
        async with sse_client(server_url + "/sse") as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                all_keys = await mock_redis.keys("*")  # type: ignore
                for key in all_keys:
                    if key.startswith("mcp:pubsub:session_active:"):
                        session_keys_seen.add(key)
                        value = await mock_redis.get(key)  # type: ignore
                        assert value == "1"

        await anyio.sleep(0.1)  # Give time for cleanup
        all_keys = await mock_redis.keys("*")  # type: ignore
        assert (
            len(all_keys) == 0
        ), f"Session keys should be cleaned up, found: {all_keys}"

    # Verify we saw different session keys for each session
    assert len(session_keys_seen) == 3, "Should have seen 3 unique session keys"


@pytest.mark.anyio
async def concurrent_tool_call(server_and_redis, server_url: str) -> None:
    """Test multiple clients and verify Redis key management."""
    mock_redis, _ = server_and_redis

    async def client_task(client_id: int) -> str:
        async with sse_client(server_url + "/sse") as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                result = await session.call_tool(
                    "echo_message",
                    {"message": f"Message from client {client_id}"},
                )
                return result.content[0].text  # type: ignore

    # Run multiple clients concurrently
    client_tasks = [client_task(i) for i in range(3)]
    results = await asyncio.gather(*client_tasks)

    # Verify all clients received their respective messages
    assert len(results) == 3
    for i, result in enumerate(results):
        assert result == f"Echo: Message from client {i}"

    # After all clients disconnect, keys should be cleaned up
    await anyio.sleep(0.1)  # Give time for cleanup
    all_keys = await mock_redis.keys("*")  # type: ignore
    assert len(all_keys) == 0, f"Session keys should be cleaned up, found: {all_keys}"
