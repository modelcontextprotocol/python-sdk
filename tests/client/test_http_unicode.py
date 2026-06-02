"""Tests for Unicode handling in streamable HTTP transport.

Verifies that Unicode text is correctly transmitted and received in both directions
(server→client and client→server) using the streamable HTTP transport.
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from tests.test_helpers import run_uvicorn_in_thread

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


def make_unicode_server_app() -> Starlette:  # pragma: no cover
    """Create the Unicode test server."""
    # Need to recreate the server setup in this process
    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                Tool(
                    name="echo_unicode",
                    description="🔤 Echo Unicode text - Hello 👋 World 🌍 - Testing 🧪 Unicode ✨",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Text to echo back"},
                        },
                        "required": ["text"],
                    },
                ),
            ]
        )

    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name == "echo_unicode":
            text = params.arguments.get("text", "") if params.arguments else ""
            return types.CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Echo: {text}",
                    )
                ]
            )
        else:
            raise ValueError(f"Unknown tool: {params.name}")

    async def handle_list_prompts(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(
            prompts=[
                types.Prompt(
                    name="unicode_prompt",
                    description="Unicode prompt - Слой хранилища, где располагаются",
                    arguments=[],
                )
            ]
        )

    async def handle_get_prompt(
        ctx: ServerRequestContext, params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        if params.name == "unicode_prompt":
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
        raise ValueError(f"Unknown prompt: {params.name}")

    server = Server(
        name="unicode_test_server",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
        on_list_prompts=handle_list_prompts,
        on_get_prompt=handle_get_prompt,
    )

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

    return app


@pytest.fixture
def running_unicode_server() -> Generator[str, None, None]:
    """Start a Unicode test server without preselecting a port."""
    with run_uvicorn_in_thread(make_unicode_server_app()) as url:
        yield url


@pytest.mark.anyio
async def test_streamable_http_client_unicode_tool_call(running_unicode_server: str) -> None:
    """Test that Unicode text is correctly handled in tool calls via streamable HTTP."""
    base_url = running_unicode_server
    endpoint_url = f"{base_url}/mcp"

    async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
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

    async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
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
