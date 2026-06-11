"""Cursor pagination of the list operations against the low-level Server.

The cursor is an opaque string chosen by the server: the suite only asserts that whatever the
handler returns as next_cursor comes back verbatim on the client's next call, not any particular
pagination scheme.
"""

import pytest
from inline_snapshot import snapshot

from mcp import McpError
from mcp.server import Server
from mcp.types import (
    INVALID_PARAMS,
    ErrorData,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsRequest,
    ListToolsResult,
    PaginatedRequestParams,
    Prompt,
    Resource,
    Tool,
)
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

    server = Server("paginated")

    @server.list_tools()
    async def list_tools(request: ListToolsRequest) -> ListToolsResult:
        received = request.params.cursor if request.params is not None else None
        seen_cursors.append(received)
        if received is None:
            return ListToolsResult(
                tools=[Tool(name="alpha", inputSchema={"type": "object"})],
                nextCursor=cursor,
            )
        return ListToolsResult(tools=[Tool(name="beta", inputSchema={"type": "object"})])

    async with connect(server) as client:
        first_page = await client.list_tools()
        second_page = await client.list_tools(params=PaginatedRequestParams(cursor=first_page.nextCursor))

    assert first_page.nextCursor == cursor
    assert seen_cursors == [None, cursor]
    assert [tool.name for tool in first_page.tools] == ["alpha"]
    assert second_page == snapshot(ListToolsResult(tools=[Tool(name="beta", inputSchema={"type": "object"})]))


@requirement("pagination:exhaustion")
@requirement("tools:list:pagination")
async def test_paginating_until_next_cursor_is_absent_yields_every_page(connect: Connect) -> None:
    """Following next_cursor until it is absent visits every page exactly once, in order."""
    pages: dict[str | None, tuple[str, str | None]] = {
        None: ("alpha", "page-2"),
        "page-2": ("beta", "page-3"),
        "page-3": ("gamma", None),
    }

    server = Server("paginated")

    @server.list_tools()
    async def list_tools(request: ListToolsRequest) -> ListToolsResult:
        received = request.params.cursor if request.params is not None else None
        tool_name, next_cursor = pages[received]
        return ListToolsResult(tools=[Tool(name=tool_name, inputSchema={"type": "object"})], nextCursor=next_cursor)

    collected: list[str] = []
    cursor: str | None = None
    requests_made = 0
    async with connect(server) as client:
        while True:
            result = await client.list_tools(params=PaginatedRequestParams(cursor=cursor))
            requests_made += 1
            assert requests_made <= len(pages), "the server kept returning next_cursor past the last page"
            collected.extend(tool.name for tool in result.tools)
            if result.nextCursor is None:
                break
            cursor = result.nextCursor

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

    server = Server("paginated")

    @server.list_tools()
    async def list_tools(request: ListToolsRequest) -> ListToolsResult:
        received = request.params.cursor if request.params is not None else None
        received_cursors.append(received)
        names, next_cursor = pages[received]
        return ListToolsResult(
            tools=[Tool(name=name, inputSchema={"type": "object"}) for name in names], nextCursor=next_cursor
        )

    page_sizes: list[int] = []
    cursor: str | None = None
    async with connect(server) as client:
        while True:
            result = await client.list_tools(params=PaginatedRequestParams(cursor=cursor))
            page_sizes.append(len(result.tools))
            if result.nextCursor is None:
                break
            cursor = result.nextCursor

    # Identity, not a snapshot: what arrived at the handler is exactly what the handler issued.
    assert received_cursors == [None, cursor_to_page_2, cursor_to_page_3]
    assert page_sizes == [3, 1, 2]


@requirement("pagination:invalid-cursor")
async def test_an_unrecognized_pagination_cursor_is_rejected_with_invalid_params(connect: Connect) -> None:
    """A list request with a cursor the server did not issue is answered with -32602 Invalid params.

    The lowlevel server does not validate cursors itself (they are opaque to it); rejecting an
    unrecognized cursor is the handler's job, and this test pins the spec-recommended way to do it.
    """

    server = Server("paginated")

    @server.list_tools()
    async def list_tools(request: ListToolsRequest) -> ListToolsResult:
        assert request.params is not None
        assert request.params.cursor == "never-issued"
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown cursor: {request.params.cursor!r}"))

    async with connect(server) as client:
        with pytest.raises(McpError) as exc_info:
            await client.list_tools(params=PaginatedRequestParams(cursor="never-issued"))

    assert exc_info.value.error.code == INVALID_PARAMS


@requirement("resources:list:pagination")
async def test_resources_list_supports_cursor_pagination(connect: Connect) -> None:
    """resources/list round-trips the cursor like every other list operation."""
    cursor = "page-2"
    seen_cursors: list[str | None] = []

    server = Server("paginated")

    @server.list_resources()
    async def list_resources(request: ListResourcesRequest) -> ListResourcesResult:
        received = request.params.cursor if request.params is not None else None
        seen_cursors.append(received)
        if received is None:
            return ListResourcesResult(resources=[Resource(uri="memo://1", name="first")], nextCursor=cursor)
        return ListResourcesResult(resources=[Resource(uri="memo://2", name="second")])

    async with connect(server) as client:
        first_page = await client.list_resources()
        second_page = await client.list_resources(params=PaginatedRequestParams(cursor=first_page.nextCursor))

    assert first_page.nextCursor == cursor
    assert seen_cursors == [None, cursor]
    assert [resource.name for resource in first_page.resources] == ["first"]
    assert [resource.name for resource in second_page.resources] == ["second"]
    assert second_page.nextCursor is None


@requirement("prompts:list:pagination")
async def test_prompts_list_supports_cursor_pagination(connect: Connect) -> None:
    """prompts/list round-trips the cursor like every other list operation."""
    cursor = "page-2"
    seen_cursors: list[str | None] = []

    server = Server("paginated")

    @server.list_prompts()
    async def list_prompts(request: ListPromptsRequest) -> ListPromptsResult:
        received = request.params.cursor if request.params is not None else None
        seen_cursors.append(received)
        if received is None:
            return ListPromptsResult(prompts=[Prompt(name="first")], nextCursor=cursor)
        return ListPromptsResult(prompts=[Prompt(name="second")])

    async with connect(server) as client:
        first_page = await client.list_prompts()
        second_page = await client.list_prompts(params=PaginatedRequestParams(cursor=first_page.nextCursor))

    assert first_page.nextCursor == cursor
    assert seen_cursors == [None, cursor]
    assert [prompt.name for prompt in first_page.prompts] == ["first"]
    assert [prompt.name for prompt in second_page.prompts] == ["second"]
    assert second_page.nextCursor is None
