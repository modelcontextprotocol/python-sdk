"""Tests for list_all_* auto-pagination helpers with safety guards."""

from __future__ import annotations

import pytest
from mcp_types import (
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    RequestParamsMeta,
)

from mcp.client.caching import CacheMode
from mcp.client.client import Client, CursorCycleError, PaginationExceededError
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


@pytest.fixture
def multi_item_server() -> MCPServer:
    """Server with several tools, resources, prompts, and templates."""
    server = MCPServer("paginated-test")

    @server.tool()
    def tool_a() -> str:  # pragma: no cover
        """Tool A."""
        return "a"

    @server.tool()
    def tool_b() -> str:  # pragma: no cover
        """Tool B."""
        return "b"

    @server.tool()
    def tool_c() -> str:  # pragma: no cover
        """Tool C."""
        return "c"

    @server.resource("test://r1")
    def res1() -> str:  # pragma: no cover
        """Resource 1."""
        return "r1"

    @server.resource("test://r2")
    def res2() -> str:  # pragma: no cover
        """Resource 2."""
        return "r2"

    @server.prompt()
    def prompt_a() -> str:  # pragma: no cover
        """Prompt A."""
        return "pa"

    @server.resource("test://tmpl/{id}")
    def tmpl(id: str) -> str:  # pragma: no cover
        """Template."""
        return f"t-{id}"

    return server


async def test_list_all_tools_returns_all(multi_item_server: MCPServer) -> None:
    """list_all_tools drains all pages and returns a flat result."""
    async with Client(multi_item_server, mode="legacy") as client:
        result = await client.list_all_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 3
        assert result.next_cursor is None


async def test_list_all_resources_returns_all(multi_item_server: MCPServer) -> None:
    """list_all_resources drains all pages."""
    async with Client(multi_item_server, mode="legacy") as client:
        result = await client.list_all_resources()
        assert isinstance(result, ListResourcesResult)
        assert len(result.resources) == 2
        assert result.next_cursor is None


async def test_list_all_prompts_returns_all(multi_item_server: MCPServer) -> None:
    """list_all_prompts drains all pages."""
    async with Client(multi_item_server, mode="legacy") as client:
        result = await client.list_all_prompts()
        assert isinstance(result, ListPromptsResult)
        assert len(result.prompts) == 1
        assert result.next_cursor is None


async def test_list_all_resource_templates_returns_all(multi_item_server: MCPServer) -> None:
    """list_all_resource_templates drains all pages."""
    async with Client(multi_item_server, mode="legacy") as client:
        result = await client.list_all_resource_templates()
        assert isinstance(result, ListResourceTemplatesResult)
        assert len(result.resource_templates) == 1
        assert result.next_cursor is None


async def test_list_all_empty_server() -> None:
    """list_all_* on a server with no items returns empty lists."""
    server = MCPServer("empty-test")
    async with Client(server, mode="legacy") as client:
        tools = await client.list_all_tools()
        assert tools.tools == []
        assert tools.next_cursor is None

        resources = await client.list_all_resources()
        assert resources.resources == []

        prompts = await client.list_all_prompts()
        assert prompts.prompts == []

        templates = await client.list_all_resource_templates()
        assert templates.resource_templates == []


async def test_list_all_max_pages_exceeded() -> None:
    """PaginationExceededError when the server doesn't terminate within max_pages."""
    server = MCPServer("infinite-test")

    @server.tool()
    def dummy() -> str:  # pragma: no cover
        """A dummy tool."""
        return "x"

    async with Client(server, mode="legacy", list_max_pages=2) as client:
        original = client.list_tools
        call_count = 0

        async def infinite_list_tools(
            *,
            cursor: str | None = None,
            meta: RequestParamsMeta | None = None,
            cache_mode: CacheMode = "use",
        ) -> ListToolsResult:
            nonlocal call_count
            call_count += 1
            result = await original(cursor=cursor, meta=meta, cache_mode=cache_mode)
            result.next_cursor = f"cursor-{call_count}"
            return result

        client.list_tools = infinite_list_tools  # type: ignore[method-assign]
        with pytest.raises(PaginationExceededError, match=r"exceeded list_max_pages \(2\)") as exc_info:
            await client.list_all_tools()
        assert exc_info.value.method == "tools/list"
        assert exc_info.value.max_pages == 2


async def test_list_all_cursor_cycle_detected() -> None:
    """CursorCycleError when the server returns a repeated cursor."""
    server = MCPServer("cycle-test")

    @server.tool()
    def dummy() -> str:  # pragma: no cover
        """A dummy tool."""
        return "x"

    async with Client(server, mode="legacy", list_max_pages=0) as client:
        original = client.list_tools
        cursors_seq = ["cursorA", "cursorB", "cursorA", "cursorA", "cursorA"]
        call_count = 0

        async def cycling_list_tools(
            *,
            cursor: str | None = None,
            meta: RequestParamsMeta | None = None,
            cache_mode: CacheMode = "use",
        ) -> ListToolsResult:
            nonlocal call_count
            call_count += 1
            result = await original(cursor=cursor, meta=meta, cache_mode=cache_mode)
            result.next_cursor = cursors_seq[call_count - 1]  # pragma: no branch
            return result

        client.list_tools = cycling_list_tools  # type: ignore[method-assign]
        with pytest.raises(CursorCycleError, match=r"cursor cycle.*cursorA") as exc_info:
            await client.list_all_tools()
        assert exc_info.value.method == "tools/list"
        assert exc_info.value.cursor == "cursorA"


async def test_list_all_unlimited_with_zero_max_pages() -> None:
    """list_max_pages=0 disables the page cap (unlimited)."""
    server = MCPServer("unlimited-test")

    @server.tool()
    def dummy() -> str:  # pragma: no cover
        """A dummy tool."""
        return "x"

    async with Client(server, mode="legacy", list_max_pages=0) as client:
        result = await client.list_all_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 1


async def test_list_all_strips_terminal_cursor() -> None:
    """The aggregated result has next_cursor=None."""
    server = MCPServer("strip-test")
    async with Client(server, mode="legacy") as client:
        result = await client.list_all_tools()
        assert result.next_cursor is None
