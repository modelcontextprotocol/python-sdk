"""Cursor pagination of the list operations against the low-level Server.

The cursor is an opaque string chosen by the server: the suite only asserts that whatever the
handler returns as next_cursor comes back verbatim on the client's next call, not any particular
pagination scheme.
"""

import pytest
from inline_snapshot import snapshot

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
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("pagination:cursor-round-trip")
async def test_next_cursor_round_trips_through_the_client() -> None:
    """The next_cursor a list handler returns reaches the client, and the cursor the client sends
    back on the following call reaches the handler verbatim.
    """
    seen_cursors: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None  # the client always sends params, even without a cursor
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListToolsResult(
                tools=[Tool(name="alpha", input_schema={"type": "object"})],
                next_cursor="page-2",
            )
        return ListToolsResult(tools=[Tool(name="beta", input_schema={"type": "object"})])

    server = Server("paginated", on_list_tools=list_tools)

    async with Client(server) as client:
        first_page = await client.list_tools()
        second_page = await client.list_tools(cursor="page-2")

    assert first_page == snapshot(
        ListToolsResult(tools=[Tool(name="alpha", input_schema={"type": "object"})], next_cursor="page-2")
    )
    assert second_page == snapshot(ListToolsResult(tools=[Tool(name="beta", input_schema={"type": "object"})]))
    assert seen_cursors == snapshot([None, "page-2"])


@requirement("pagination:exhaustion")
async def test_paginating_until_next_cursor_is_absent_yields_every_page() -> None:
    """Following next_cursor until it is absent visits every page exactly once, in order."""
    pages: dict[str | None, tuple[str, str | None]] = {
        None: ("alpha", "page-2"),
        "page-2": ("beta", "page-3"),
        "page-3": ("gamma", None),
    }

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        tool_name, next_cursor = pages[params.cursor]
        return ListToolsResult(tools=[Tool(name=tool_name, input_schema={"type": "object"})], next_cursor=next_cursor)

    server = Server("paginated", on_list_tools=list_tools)

    collected: list[str] = []
    cursor: str | None = None
    requests_made = 0
    async with Client(server) as client:
        while True:
            result = await client.list_tools(cursor=cursor)
            requests_made += 1
            assert requests_made <= len(pages), "the server kept returning next_cursor past the last page"
            collected.extend(tool.name for tool in result.tools)
            if result.next_cursor is None:
                break
            cursor = result.next_cursor

    assert collected == snapshot(["alpha", "beta", "gamma"])
    assert requests_made == len(pages)


@requirement("pagination:resources")
async def test_resources_list_supports_cursor_pagination() -> None:
    """resources/list round-trips the cursor like every other list operation."""
    seen_cursors: list[str | None] = []

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListResourcesResult(resources=[Resource(uri="memo://1", name="first")], next_cursor="page-2")
        return ListResourcesResult(resources=[Resource(uri="memo://2", name="second")])

    server = Server("paginated", on_list_resources=list_resources)

    async with Client(server) as client:
        first_page = await client.list_resources()
        second_page = await client.list_resources(cursor="page-2")

    assert seen_cursors == snapshot([None, "page-2"])
    assert [resource.name for resource in first_page.resources] == ["first"]
    assert first_page.next_cursor == "page-2"
    assert [resource.name for resource in second_page.resources] == ["second"]
    assert second_page.next_cursor is None


@requirement("pagination:resource-templates")
async def test_resource_templates_list_supports_cursor_pagination() -> None:
    """resources/templates/list round-trips the cursor like every other list operation."""
    seen_cursors: list[str | None] = []

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListResourceTemplatesResult(
                resource_templates=[ResourceTemplate(name="first", uri_template="users://{id}")],
                next_cursor="page-2",
            )
        return ListResourceTemplatesResult(
            resource_templates=[ResourceTemplate(name="second", uri_template="teams://{id}")]
        )

    server = Server("paginated", on_list_resource_templates=list_resource_templates)

    async with Client(server) as client:
        first_page = await client.list_resource_templates()
        second_page = await client.list_resource_templates(cursor="page-2")

    assert seen_cursors == snapshot([None, "page-2"])
    assert [template.name for template in first_page.resource_templates] == ["first"]
    assert first_page.next_cursor == "page-2"
    assert [template.name for template in second_page.resource_templates] == ["second"]
    assert second_page.next_cursor is None


@requirement("pagination:prompts")
async def test_prompts_list_supports_cursor_pagination() -> None:
    """prompts/list round-trips the cursor like every other list operation."""
    seen_cursors: list[str | None] = []

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListPromptsResult(prompts=[Prompt(name="first")], next_cursor="page-2")
        return ListPromptsResult(prompts=[Prompt(name="second")])

    server = Server("paginated", on_list_prompts=list_prompts)

    async with Client(server) as client:
        first_page = await client.list_prompts()
        second_page = await client.list_prompts(cursor="page-2")

    assert seen_cursors == snapshot([None, "page-2"])
    assert [prompt.name for prompt in first_page.prompts] == ["first"]
    assert first_page.next_cursor == "page-2"
    assert [prompt.name for prompt in second_page.prompts] == ["second"]
    assert second_page.next_cursor is None
