"""
Tests for Unicode handling in streamable HTTP transport.

Verifies that Unicode text is correctly transmitted and received in both directions
(server→client and client→server) using the streamable HTTP transport.
"""

import multiprocessing
import socket
import time
from collections.abc import Generator

import pytest

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Test constants with various Unicode characters
UNICODE_TEST_STRINGS = {
    "cyrillic": "Слой хранилища, где располагаются",
    "cyrillic_short": "Привет мир",
    "chinese": "你好世界 - 这是一个测试",
    "japanese": "こんにちは世界 - これはテストです",
    "korean": "안녕하세요 세계 - 이것은 테스트입니다",
    "arabic": "مرحبا بالعالم - هذا اختبار",
    "hebrew": "שלום עולם - זה מבחן",
    "greek": "Γεια σου κόσμε - αυτό είναι δοκιμή",
    "emoji": "Hello 👋 World 🌍 - Testing 🧪 Unicode ✨",
    "math": "∑ ∫ √ ∞ ≠ ≤ ≥ ∈ ∉ ⊆ ⊇",
    "accented": "Café, naïve, résumé, piñata, Zürich",
    "mixed": "Hello世界🌍Привет안녕مرحباשלום",
    "special": "Line\nbreak\ttab\r\nCRLF",
    "quotes": '«French» „German" "English" 「Japanese」',
    "currency": "€100 £50 ¥1000 ₹500 ₽200 ¢99",
}


def run_unicode_server(port: int) -> None:
    """Run the Unicode test server in a separate process."""
    # Import inside the function since this runs in a separate process
    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager
    from typing import Any

    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount

    import mcp.types as types
    from mcp.server import Server
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.types import TextContent, Tool

    # Need to recreate the server setup in this process
    server = Server(name="unicode_test_server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List tools with Unicode descriptions."""
        return [
            Tool(
                name="echo_unicode",
                description="🔤 Echo Unicode text - Hello 👋 World 🌍 - Testing 🧪 Unicode ✨",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to echo back"},
                    },
                    "required": ["text"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        """Handle tool calls with Unicode content."""
        if name == "echo_unicode":
            text = arguments.get("text", "") if arguments else ""
            return [
                TextContent(
                    type="text",
                    text=f"Echo: {text}",
                )
            ]
        else:
            raise ValueError(f"Unknown tool: {name}")

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        """List prompts with Unicode names and descriptions."""
        return [
            types.Prompt(
                name="unicode_prompt",
                description="Unicode prompt - Слой хранилища, где располагаются",
                arguments=[],
            )
        ]

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, Any] | None) -> types.GetPromptResult:
        """Get a prompt with Unicode content."""
        if name == "unicode_prompt":
            return types.GetPromptResult(
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(
                            type="text",
                            text="Hello世界🌍Привет안녕مرحباשלום",
                        ),
                    )
                ]
            )
        raise ValueError(f"Unknown prompt: {name}")

    # Create the session manager
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,  # Use SSE for testing
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    # Create an ASGI application
    app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )

    # Run the server
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    uvicorn_server = uvicorn.Server(config)
    uvicorn_server.run()


@pytest.fixture
def unicode_server_port() -> int:
    """Find an available port for the Unicode test server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running_unicode_server(unicode_server_port: int) -> Generator[str, None, None]:
    """Start a Unicode test server in a separate process."""
    proc = multiprocessing.Process(target=run_unicode_server, kwargs={"port": unicode_server_port}, daemon=True)
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", unicode_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    try:
        yield f"http://127.0.0.1:{unicode_server_port}"
    finally:
        # Clean up - try graceful termination first
        proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1)


@pytest.mark.anyio
async def test_streamable_http_client_unicode_tool_call(running_unicode_server: str) -> None:
    """Test that Unicode text is correctly handled in tool calls via streamable HTTP."""
    base_url = running_unicode_server
    endpoint_url = f"{base_url}/mcp"

    async with streamable_http_client(endpoint_url) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test 1: List tools (server→client Unicode in descriptions)
            tools = await session.list_tools()
            assert len(tools.tools) == 1

            # Check Unicode in tool descriptions
            echo_tool = tools.tools[0]
            assert echo_tool.name == "echo_unicode"
            assert echo_tool.description is not None
            assert "🔤" in echo_tool.description
            assert "👋" in echo_tool.description

            # Test 2: Send Unicode text in tool call (client→server→client)
            for test_name, test_string in UNICODE_TEST_STRINGS.items():
                result = await session.call_tool("echo_unicode", arguments={"text": test_string})

                # Verify server correctly received and echoed back Unicode
                assert len(result.content) == 1
                content = result.content[0]
                assert content.type == "text"
                assert f"Echo: {test_string}" == content.text, f"Failed for {test_name}"


@pytest.mark.anyio
async def test_streamable_http_client_unicode_prompts(running_unicode_server: str) -> None:
    """Test that Unicode text is correctly handled in prompts via streamable HTTP."""
    base_url = running_unicode_server
    endpoint_url = f"{base_url}/mcp"

    async with streamable_http_client(endpoint_url) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test 1: List prompts (server→client Unicode in descriptions)
            prompts = await session.list_prompts()
            assert len(prompts.prompts) == 1

            prompt = prompts.prompts[0]
            assert prompt.name == "unicode_prompt"
            assert prompt.description is not None
            assert "Слой хранилища, где располагаются" in prompt.description

            # Test 2: Get prompt with Unicode content (server→client)
            result = await session.get_prompt("unicode_prompt", arguments={})
            assert len(result.messages) == 1

            message = result.messages[0]
            assert message.role == "user"
            assert message.content.type == "text"
            assert message.content.text == "Hello世界🌍Привет안녕مرحباשלום"
