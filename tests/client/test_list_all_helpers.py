"""Tests for the list_all_* helpers on Client that drain pagination automatically."""

import pytest

from mcp import types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    Prompt,
    Resource,
    ResourceTemplate,
    Tool,
)

pytestmark = pytest.mark.anyio


async def test_list_all_tools_drains_pagination() -> None:
    """list_all_tools follows next_cursor and returns all tools across pages."""
    pages: dict[str | None, tuple[list[str], str | None]] = {
        None: (["alpha", "beta"], "page-2"),
        "page-2": (["gamma"], None),
    }

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        names, next_cursor = pages[params.cursor]
        return ListToolsResult(
            tools=[Tool(name=n, input_schema={"type": "object"}) for n in names],
            next_cursor=next_cursor,
        )

    server = Server("paginated", on_list_tools=list_tools)

    async with Client(server) as client:
        result = await client.list_all_tools()

    assert [t.name for t in result.tools] == ["alpha", "beta", "gamma"]
    assert result.next_cursor is None


async def test_list_all_tools_single_page() -> None:
    """list_all_tools works when the server returns all tools in a single page."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name="only", input_schema={"type": "object"}),
            ]
        )

    server = Server("single", on_list_tools=list_tools)

    async with Client(server) as client:
        result = await client.list_all_tools()

    assert [t.name for t in result.tools] == ["only"]


async def test_list_all_tools_empty() -> None:
    """list_all_tools returns an empty list when the server has no tools."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    server = Server("empty", on_list_tools=list_tools)

    async with Client(server) as client:
        result = await client.list_all_tools()

    assert result.tools == []


async def test_list_all_resources_drains_pagination() -> None:
    """list_all_resources follows next_cursor and returns all resources across pages."""
    pages: dict[str | None, tuple[list[str], str | None]] = {
        None: (["res-a"], "page-2"),
        "page-2": (["res-b", "res-c"], None),
    }

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        assert params is not None
        names, next_cursor = pages[params.cursor]
        return ListResourcesResult(
            resources=[Resource(uri=f"test://{n}", name=n) for n in names],
            next_cursor=next_cursor,
        )

    server = Server("paginated", on_list_resources=list_resources)

    async with Client(server) as client:
        result = await client.list_all_resources()

    assert [r.name for r in result.resources] == ["res-a", "res-b", "res-c"]


async def test_list_all_resource_templates_drains_pagination() -> None:
    """list_all_resource_templates follows next_cursor and returns all templates across pages."""
    pages: dict[str | None, tuple[list[str], str | None]] = {
        None: (["tmpl-a"], "page-2"),
        "page-2": (["tmpl-b"], None),
    }

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        assert params is not None
        names, next_cursor = pages[params.cursor]
        return ListResourceTemplatesResult(
            resource_templates=[ResourceTemplate(name=n, uri_template=f"{n}://{{id}}") for n in names],
            next_cursor=next_cursor,
        )

    server = Server("paginated", on_list_resource_templates=list_resource_templates)

    async with Client(server) as client:
        result = await client.list_all_resource_templates()

    assert [t.name for t in result.resource_templates] == ["tmpl-a", "tmpl-b"]


async def test_list_all_prompts_drains_pagination() -> None:
    """list_all_prompts follows next_cursor and returns all prompts across pages."""
    pages: dict[str | None, tuple[list[str], str | None]] = {
        None: (["greet", "farewell"], "page-2"),
        "page-2": (["summarize"], None),
    }

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        assert params is not None
        names, next_cursor = pages[params.cursor]
        return ListPromptsResult(
            prompts=[Prompt(name=n) for n in names],
            next_cursor=next_cursor,
        )

    server = Server("paginated", on_list_prompts=list_prompts)

    async with Client(server) as client:
        result = await client.list_all_prompts()

    assert [p.name for p in result.prompts] == ["greet", "farewell", "summarize"]


async def test_list_all_tools_populates_output_schema_cache() -> None:
    """list_all_tools populates the tool output-schema cache (same as list_tools)."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="cached_tool",
                    input_schema={"type": "object"},
                    output_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
                ),
            ]
        )

    server = Server("schema-cache", on_list_tools=list_tools)

    async with Client(server) as client:
        await client.list_all_tools()
        # The cache should be populated
        assert "cached_tool" in client.session._tool_output_schemas
