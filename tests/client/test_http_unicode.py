"""
Tests for Unicode handling in streamable HTTP transport.

Verifies that Unicode text is correctly transmitted and received in both directions
(server→client and client→server) using the streamable HTTP transport.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sse_starlette.sse import AppStatus
from starlette.applications import Starlette
from starlette.routing import Mount

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import CallToolResult, TextContent, Tool
from tests.interaction.transports import StreamingASGITransport

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"

# v1's streamable-HTTP server transport leaks a handful of anyio memory streams on teardown when
# run in process; the old subprocess harness never observed them. The interaction suite registers
# the same two scoped filters globally from tests/interaction/conftest.py (see the comment there),
# but they only take effect when that package's conftest is loaded; these markers keep the tests
# themselves passing in isolated runs. Markers are item-scoped, so they cannot cover the GC
# flush at session cleanup: an isolated run without xdist (`-n 0`) still exits nonzero after all
# tests pass. The default xdist runs (addopts has `-n auto`) are unaffected, as are full-suite
# runs, where the interaction conftest's ini-level filters apply. The filters are scoped to
# anyio's MemoryObject*Stream leak signature so an unrelated leak still fails the suite.
pytestmark = [
    pytest.mark.filterwarnings("ignore:.*MemoryObject(Send|Receive)Stream:pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore:.*MemoryObject(Send|Receive)Stream:ResourceWarning"),
]


@pytest.fixture(autouse=True)
def _reset_sse_starlette_exit_event() -> Iterator[None]:
    """Reset sse-starlette's module-global exit Event around each test.

    sse-starlette <3.0 (allowed by this branch's dependency floor; CI's lowest-direct leg
    installs it) stores an `anyio.Event` on the `AppStatus` class the first time an
    `EventSourceResponse` runs; that Event is bound to the test's event loop and breaks every
    subsequent in-process SSE response (and `json_response=False` below means every request
    in this module is served as one). sse-starlette 3.x switched to a ContextVar and has no
    such attribute. Resetting on both sides of the test keeps this module immune to a stale
    Event left behind by an earlier test on the same worker as well as cleaning up after its
    own. This mirrors the autouse fixtures in tests/shared/test_sse.py and
    tests/interaction/conftest.py.
    """
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        # setattr keeps pyright happy: the locked sse-starlette 3.x has no such attribute.
        setattr(AppStatus, "should_exit_event", None)  # pragma: lax no cover
    yield
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        setattr(AppStatus, "should_exit_event", None)  # pragma: lax no cover


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


def make_unicode_server() -> Server[object, object]:
    """The Unicode echo server: tool and prompt contents that exercise non-ASCII round trips."""
    server: Server[object, object] = Server(name="unicode_test_server")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
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
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "echo_unicode"
        return CallToolResult(content=[TextContent(type="text", text=f"Echo: {arguments['text']}")])

    @server.list_prompts()
    async def handle_list_prompts() -> list[types.Prompt]:
        return [
            types.Prompt(
                name="unicode_prompt",
                description="Unicode prompt - Слой хранилища, где располагаются",
                arguments=[],
            )
        ]

    @server.get_prompt()
    async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        assert name == "unicode_prompt"
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text="Hello世界🌍Привет안녕مرحباשלום"),
                )
            ]
        )

    return server


@asynccontextmanager
async def unicode_session() -> AsyncIterator[ClientSession]:
    """Yield an initialized ClientSession speaking streamable HTTP (SSE responses) to the
    Unicode test server, entirely in process."""
    # SSE response mode, so Unicode rides the SSE event encoding rather than a plain JSON body.
    session_manager = StreamableHTTPSessionManager(app=make_unicode_server(), json_response=False)
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])

    async with (
        session_manager.run(),
        # follow_redirects matches the SDK's own client factory; Starlette's Mount 307-redirects
        # the bare /mcp path to /mcp/.
        httpx.AsyncClient(
            transport=StreamingASGITransport(app), base_url=BASE_URL, follow_redirects=True
        ) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (
            read_stream,
            write_stream,
            _get_session_id,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


@pytest.mark.anyio
async def test_streamable_http_client_unicode_tool_call() -> None:
    """Test that Unicode text is correctly handled in tool calls via streamable HTTP."""
    async with unicode_session() as session:
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
async def test_streamable_http_client_unicode_prompts() -> None:
    """Test that Unicode text is correctly handled in prompts via streamable HTTP."""
    async with unicode_session() as session:
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
