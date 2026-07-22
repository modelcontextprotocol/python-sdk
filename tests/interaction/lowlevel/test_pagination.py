"""Cursor pagination of the list operations against the low-level Server.

The cursor is an opaque string chosen by the server: the suite only asserts that whatever the
handler returns as next_cursor comes back verbatim on the client's next call, not any particular
pagination scheme.
"""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    Prompt,
    Resource,
    ResourceTemplate,
    Tool,
)

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from tests._stamp import unstamped
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:list:pagination")
async def test_next_cursor_round_trips_through_the_client(connect: Connect) -> None:
    """The next_cursor a list handler returns reaches the client, and the cursor the client sends
    back on the following call reaches the handler verbatim.
    """
    cursor = "page-2"
    seen_cursors: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None  # the client always sends params, even without a cursor
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListToolsResult(
                tools=[Tool(name="alpha", input_schema={"type": "object"})],
                next_cursor=cursor,
            )
        return ListToolsResult(tools=[Tool(name="beta", input_schema={"type": "object"})])

    server = Server("paginated", on_list_tools=list_tools)

    async with connect(server) as client:
        first_page = await client.list_tools()
        second_page = await client.list_tools(cursor=first_page.next_cursor)

    assert first_page.next_cursor == cursor
    assert seen_cursors == [None, cursor]
    assert [tool.name for tool in first_page.tools] == ["alpha"]
    assert unstamped(second_page) == snapshot(
        ListToolsResult(tools=[Tool(name="beta", input_schema={"type": "object"})])
    )


@requirement("pagination:exhaustion")
@requirement("tools:list:pagination")
async def test_paginating_until_next_cursor_is_absent_yields_every_page(connect: Connect) -> None:
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
    async with connect(server) as client:
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


@requirement("pagination:client:cursor-handling")
async def test_the_client_follows_opaque_cursors_through_pages_of_varying_sizes(connect: Connect) -> None:
    """The client passes a server-issued cursor back byte-for-byte and follows pages of varying sizes.

    The cursors are deliberately base64-looking strings (with padding and URL-unsafe characters) to
    show the client treats them as opaque tokens; the page sizes [3, 1, 2] show the loop relies only
    on next_cursor, not on a fixed page size.
    """
    cursor_to_page_2 = "YWxwaGE+YnJhdm8/Y2hhcmxpZQ=="
    cursor_to_page_3 = "ZGVsdGE="
    pages: dict[str | None, tuple[list[str], str | None]] = {
        None: (["alpha", "beta", "gamma"], cursor_to_page_2),
        cursor_to_page_2: (["delta"], cursor_to_page_3),
        cursor_to_page_3: (["epsilon", "zeta"], None),
    }
    received_cursors: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        received_cursors.append(params.cursor)
        names, next_cursor = pages[params.cursor]
        return ListToolsResult(
            tools=[Tool(name=name, input_schema={"type": "object"}) for name in names], next_cursor=next_cursor
        )

    server = Server("paginated", on_list_tools=list_tools)

    page_sizes: list[int] = []
    cursor: str | None = None
    async with connect(server) as client:
        while True:
            result = await client.list_tools(cursor=cursor)
            page_sizes.append(len(result.tools))
            if result.next_cursor is None:
                break
            cursor = result.next_cursor

    # Identity, not a snapshot: what arrived at the handler is exactly what the handler issued.
    assert received_cursors == [None, cursor_to_page_2, cursor_to_page_3]
    assert page_sizes == [3, 1, 2]


@requirement("pagination:invalid-cursor")
async def test_an_unrecognized_pagination_cursor_is_rejected_with_invalid_params(connect: Connect) -> None:
    """A list request with a cursor the server did not issue is answered with -32602 Invalid params.

    The lowlevel server does not validate cursors itself (they are opaque to it); rejecting an
    unrecognized cursor is the handler's job, and this test pins the spec-recommended way to do it.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        assert params.cursor == "never-issued"
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown cursor: {params.cursor!r}")

    server = Server("paginated", on_list_tools=list_tools)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.list_tools(cursor="never-issued")

    assert exc_info.value.error.code == INVALID_PARAMS


@requirement("resources:list:pagination")
async def test_resources_list_supports_cursor_pagination(connect: Connect) -> None:
    """resources/list round-trips the cursor like every other list operation."""
    cursor = "page-2"
    seen_cursors: list[str | None] = []

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListResourcesResult(resources=[Resource(uri="memo://1", name="first")], next_cursor=cursor)
        return ListResourcesResult(resources=[Resource(uri="memo://2", name="second")])

    server = Server("paginated", on_list_resources=list_resources)

    async with connect(server) as client:
        first_page = await client.list_resources()
        second_page = await client.list_resources(cursor=first_page.next_cursor)

    assert first_page.next_cursor == cursor
    assert seen_cursors == [None, cursor]
    assert [resource.name for resource in first_page.resources] == ["first"]
    assert [resource.name for resource in second_page.resources] == ["second"]
    assert second_page.next_cursor is None


@requirement("resources:templates:pagination")
async def test_resource_templates_list_supports_cursor_pagination(connect: Connect) -> None:
    """resources/templates/list round-trips the cursor like every other list operation."""
    cursor = "page-2"
    seen_cursors: list[str | None] = []

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListResourceTemplatesResult(
                resource_templates=[ResourceTemplate(name="first", uri_template="users://{id}")],
                next_cursor=cursor,
            )
        return ListResourceTemplatesResult(
            resource_templates=[ResourceTemplate(name="second", uri_template="teams://{id}")]
        )

    server = Server("paginated", on_list_resource_templates=list_resource_templates)

    async with connect(server) as client:
        first_page = await client.list_resource_templates()
        second_page = await client.list_resource_templates(cursor=first_page.next_cursor)

    assert first_page.next_cursor == cursor
    assert seen_cursors == [None, cursor]
    assert [template.name for template in first_page.resource_templates] == ["first"]
    assert [template.name for template in second_page.resource_templates] == ["second"]
    assert second_page.next_cursor is None


@requirement("prompts:list:pagination")
async def test_prompts_list_supports_cursor_pagination(connect: Connect) -> None:
    """prompts/list round-trips the cursor like every other list operation."""
    cursor = "page-2"
    seen_cursors: list[str | None] = []

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListPromptsResult(prompts=[Prompt(name="first")], next_cursor=cursor)
        return ListPromptsResult(prompts=[Prompt(name="second")])

    server = Server("paginated", on_list_prompts=list_prompts)

    async with connect(server) as client:
        first_page = await client.list_prompts()
        second_page = await client.list_prompts(cursor=first_page.next_cursor)

    assert first_page.next_cursor == cursor
    assert seen_cursors == [None, cursor]
    assert [prompt.name for prompt in first_page.prompts] == ["first"]
    assert [prompt.name for prompt in second_page.prompts] == ["second"]
    assert second_page.next_cursor is None
