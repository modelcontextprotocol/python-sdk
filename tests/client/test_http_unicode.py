"""Tests for Unicode handling in streamable HTTP transport.

Verifies that Unicode text is correctly transmitted and received in both directions
(server→client and client→server) using the streamable HTTP transport.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool

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


async def _handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            Tool(
                name="echo_unicode",
                description="🔤 Echo Unicode text - Hello 👋 World 🌍 - Testing 🧪 Unicode ✨",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "Text to echo back"}},
                    "required": ["text"],
                },
            ),
        ]
    )


async def _handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name == "echo_unicode":
        text = params.arguments.get("text", "") if params.arguments else ""
        return types.CallToolResult(content=[TextContent(type="text", text=f"Echo: {text}")])
    raise ValueError(f"Unknown tool: {params.name}")  # pragma: no cover


async def _handle_list_prompts(
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


async def _handle_get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> types.GetPromptResult:
    if params.name == "unicode_prompt":
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text="Hello世界🌍Привет안녕مرحباשלום"),
                )
            ]
        )
    raise ValueError(f"Unknown prompt: {params.name}")  # pragma: no cover


def _make_unicode_app() -> Starlette:
    server = Server(
        name="unicode_test_server",
        on_list_tools=_handle_list_tools,
        on_call_tool=_handle_call_tool,
        on_list_prompts=_handle_list_prompts,
        on_get_prompt=_handle_get_prompt,
    )
    session_manager = StreamableHTTPSessionManager(app=server, json_response=False)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    return Starlette(
        debug=True,
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )


@pytest.fixture
async def unicode_session() -> AsyncGenerator[ClientSession, None]:
    """Create an initialized client session connected to the in-process unicode server."""
    app = _make_unicode_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http_client:
            async with streamable_http_client(  # pragma: no branch
                "http://testserver/mcp", http_client=http_client
            ) as (rs, ws):
                # ^ coverage.py on 3.11+ misses phantom ->exit arcs from nested
                # async with CMs when the innermost body yields (async generator
                # frame unwinds through __aexit__ chains). On 3.14 the
                # WITH_EXCEPT_START suppression-check branch is misattributed
                # through the exception table to the *outer* CM line too.
                async with ClientSession(rs, ws) as session:  # pragma: no branch
                    await session.initialize()
                    yield session


@pytest.mark.anyio
async def test_streamable_http_client_unicode_tool_call(unicode_session: ClientSession) -> None:
    """Test that Unicode text is correctly handled in tool calls via streamable HTTP."""
    # Test 1: List tools (server→client Unicode in descriptions)
    tools = await unicode_session.list_tools()
    assert len(tools.tools) == 1

    echo_tool = tools.tools[0]
    assert echo_tool.name == "echo_unicode"
    assert echo_tool.description is not None
    assert "🔤" in echo_tool.description
    assert "👋" in echo_tool.description

    # Test 2: Send Unicode text in tool call (client→server→client)
    for test_name, test_string in UNICODE_TEST_STRINGS.items():
        result = await unicode_session.call_tool("echo_unicode", arguments={"text": test_string})
        assert len(result.content) == 1
        content = result.content[0]
        assert content.type == "text"
        assert f"Echo: {test_string}" == content.text, f"Failed for {test_name}"


@pytest.mark.anyio
async def test_streamable_http_client_unicode_prompts(unicode_session: ClientSession) -> None:
    """Test that Unicode text is correctly handled in prompts via streamable HTTP."""
    # Test 1: List prompts (server→client Unicode in descriptions)
    prompts = await unicode_session.list_prompts()
    assert len(prompts.prompts) == 1

    prompt = prompts.prompts[0]
    assert prompt.name == "unicode_prompt"
    assert prompt.description is not None
    assert "Слой хранилища, где располагаются" in prompt.description

    # Test 2: Get prompt with Unicode content (server→client)
    result = await unicode_session.get_prompt("unicode_prompt", arguments={})
    assert len(result.messages) == 1

    message = result.messages[0]
    assert message.role == "user"
    assert message.content.type == "text"
    assert message.content.text == "Hello世界🌍Привет안녕مرحباשלום"
