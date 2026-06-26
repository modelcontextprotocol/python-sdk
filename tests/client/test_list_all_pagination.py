"""Tests for client `list_all_*` and `iter_all_*` pagination helpers.

These helpers drain `next_cursor` across pages, so a server can split
its tools/prompts/resources/resource_templates across multiple list
calls and the client still sees the full collection.

See: https://github.com/modelcontextprotocol/python-sdk/issues/2556
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import mcp_types as types
import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext

from .conftest import StreamSpyCollection

pytestmark = pytest.mark.anyio

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


def _paginated_handler(
    pages: list[list[str]],
    make_item: Callable[[str], ItemT],
    result_cls: Callable[..., ResultT],
    items_field: str,
) -> Callable[[ServerRequestContext, types.PaginatedRequestParams | None], Awaitable[ResultT]]:
    """Build a lowlevel-server handler that serves `pages` of items.

    Each page advances `next_cursor` from `"1"` ... `"N-1"` and the last
    page returns no cursor. The handler is keyed by the cursor it receives
    in the request, so cursor handling on both sides is exercised.
    """
    # Map incoming cursor (None for first page) to the page index to return.
    cursor_to_page: dict[str | None, int] = {None: 0}
    for index in range(len(pages) - 1):
        cursor_to_page[str(index + 1)] = index + 1

    async def handler(_ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ResultT:
        cursor = params.cursor if params else None
        page_index = cursor_to_page[cursor]
        page = pages[page_index]
        next_cursor = str(page_index + 1) if page_index + 1 < len(pages) else None
        return result_cls(
            **{items_field: [make_item(name) for name in page]},
            next_cursor=next_cursor,
        )

    return handler


def _make_tool(name: str) -> types.Tool:
    return types.Tool(name=name, input_schema={"type": "object"})


def _make_prompt(name: str) -> types.Prompt:
    return types.Prompt(name=name)


def _make_resource(name: str) -> types.Resource:
    return types.Resource(name=name, uri=f"test://{name}")


def _make_resource_template(name: str) -> types.ResourceTemplate:
    return types.ResourceTemplate(name=name, uri_template=f"test://{name}/{{id}}")


# ---- list_all_tools / iter_all_tools ---------------------------------------


async def test_list_all_tools_drains_all_pages(
    stream_spy: Callable[[], StreamSpyCollection],
):
    """list_all_tools follows `next_cursor` and returns the union of pages."""
    pages = [["a", "b"], ["c", "d"], ["e"]]
    server = Server(
        "paginated-tools",
        on_list_tools=_paginated_handler(pages, _make_tool, types.ListToolsResult, "tools"),
    )

    async with Client(server, mode="legacy") as client:
        spies = stream_spy()
        tools = await client.list_all_tools()

        assert [t.name for t in tools] == ["a", "b", "c", "d", "e"]
        # One request per page.
        requests = spies.get_client_requests(method="tools/list")
        assert len(requests) == 3
        # First request has no cursor; subsequent ones carry the previous cursor.
        assert requests[0].params is None or "cursor" not in requests[0].params
        assert requests[1].params is not None and requests[1].params["cursor"] == "1"
        assert requests[2].params is not None and requests[2].params["cursor"] == "2"


async def test_list_all_tools_single_page():
    """A server that returns one page (no cursor) should give back one list."""

    async def handle_list_tools(
        _ctx: ServerRequestContext, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_make_tool("only")])

    server = Server("single-page-tools", on_list_tools=handle_list_tools)

    async with Client(server) as client:
        tools = await client.list_all_tools()
        assert [t.name for t in tools] == ["only"]


async def test_list_all_tools_empty_server():
    """An empty server should yield an empty list, not raise."""

    async def handle_list_tools(
        _ctx: ServerRequestContext, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    server = Server("no-tools", on_list_tools=handle_list_tools)

    async with Client(server) as client:
        tools = await client.list_all_tools()
        assert tools == []


async def test_iter_all_tools_streams_pages(
    stream_spy: Callable[[], StreamSpyCollection],
):
    """iter_all_tools yields one tool at a time and only pages when needed."""
    pages = [["a", "b"], ["c"]]
    server = Server(
        "stream-tools",
        on_list_tools=_paginated_handler(pages, _make_tool, types.ListToolsResult, "tools"),
    )

    async with Client(server, mode="legacy") as client:
        spies = stream_spy()
        seen = [tool.name async for tool in client.iter_all_tools()]

        assert seen == ["a", "b", "c"]
        assert len(spies.get_client_requests(method="tools/list")) == 2


# ---- list_all_prompts ------------------------------------------------------


async def test_list_all_prompts_drains_all_pages(
    stream_spy: Callable[[], StreamSpyCollection],
):
    pages = [["p1", "p2"], ["p3"]]
    server = Server(
        "paginated-prompts",
        on_list_prompts=_paginated_handler(pages, _make_prompt, types.ListPromptsResult, "prompts"),
    )

    async with Client(server, mode="legacy") as client:
        spies = stream_spy()
        prompts = await client.list_all_prompts()
        assert [p.name for p in prompts] == ["p1", "p2", "p3"]
        assert len(spies.get_client_requests(method="prompts/list")) == 2


# ---- list_all_resources ----------------------------------------------------


async def test_list_all_resources_drains_all_pages(
    stream_spy: Callable[[], StreamSpyCollection],
):
    pages = [["r1", "r2"], ["r3"], ["r4"]]
    server = Server(
        "paginated-resources",
        on_list_resources=_paginated_handler(pages, _make_resource, types.ListResourcesResult, "resources"),
    )

    async with Client(server, mode="legacy") as client:
        spies = stream_spy()
        resources = await client.list_all_resources()
        assert [r.name for r in resources] == ["r1", "r2", "r3", "r4"]
        assert len(spies.get_client_requests(method="resources/list")) == 3


# ---- list_all_resource_templates ------------------------------------------


async def test_list_all_resource_templates_drains_all_pages(
    stream_spy: Callable[[], StreamSpyCollection],
):
    pages = [["t1"], ["t2", "t3"]]
    server = Server(
        "paginated-templates",
        on_list_resource_templates=_paginated_handler(
            pages,
            _make_resource_template,
            types.ListResourceTemplatesResult,
            "resource_templates",
        ),
    )

    async with Client(server, mode="legacy") as client:
        spies = stream_spy()
        templates = await client.list_all_resource_templates()
        assert [t.name for t in templates] == ["t1", "t2", "t3"]
        assert len(spies.get_client_requests(method="resources/templates/list")) == 2
