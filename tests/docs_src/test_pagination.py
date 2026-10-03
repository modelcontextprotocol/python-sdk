"""`docs/advanced/pagination.md`: every claim the page makes, proved against the real SDK."""

import pytest

from docs_src.pagination import tutorial001, tutorial002
from mcp import Client, MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.resources import TextResource

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

mcp = MCPServer("Bookshop")
for n in range(1, 101):
    mcp.add_resource(TextResource(uri=f"books://catalog/book-{n}", name=f"book-{n}", text=f"book-{n}"))


async def test_mcpserver_never_pages() -> None:
    """The page's framing: `MCPServer` answers `resources/list` in one page with `next_cursor=None`."""
    async with Client(mcp) as client:
        result = await client.list_resources()
        assert len(result.resources) == 100
        assert result.next_cursor is None


async def test_first_page_has_ten_resources_and_a_cursor() -> None:
    """tutorial001: no cursor means page one: ten resources and a `next_cursor` the client may ignore."""
    async with Client(tutorial001.server) as client:
        page = await client.list_resources()
        assert [resource.name for resource in page.resources] == [f"book-{n}" for n in range(1, 11)]
        assert page.next_cursor == "10"


async def test_the_cursor_resumes_where_the_last_page_stopped() -> None:
    """tutorial001: handing `next_cursor` straight back yields the next page, no overlap."""
    async with Client(tutorial001.server) as client:
        page = await client.list_resources(cursor="10")
        assert page.resources[0].name == "book-11"
        assert page.next_cursor == "20"


async def test_the_last_page_carries_no_cursor() -> None:
    """tutorial001: `next_cursor=None` is the only end-of-list signal."""
    async with Client(tutorial001.server) as client:
        page = await client.list_resources(cursor="90")
        assert len(page.resources) == 10
        assert page.next_cursor is None


async def test_the_client_loop_collects_all_one_hundred_in_order() -> None:
    """tutorial002's `list_all_resources()`, driven in-process against tutorial001's server: the `cursor=` loop
    stitches the pages back into the whole catalog, in order, with no gaps and no repeats."""
    async with Client(tutorial001.server) as client:
        resources = await tutorial002.list_all_resources(client)
    assert [resource.name for resource in resources] == tutorial001.BOOKS


async def test_the_client_loop_runs_once_against_a_server_that_does_not_page() -> None:
    """tutorial002's loop against the `MCPServer` above: `next_cursor` is `None` on the first response, so one
    pass returns the whole catalog."""
    async with Client(mcp) as client:
        resources = await tutorial002.list_all_resources(client)
    assert [resource.name for resource in resources] == [f"book-{n}" for n in range(1, 101)]


async def test_an_invented_cursor_is_an_error() -> None:
    """Cursors are opaque: a string the server never minted blows up inside the handler."""
    async with Client(tutorial001.server) as client:
        with pytest.raises(MCPError) as excinfo:
            await client.list_resources(cursor="page-2")
        assert excinfo.value.code == -32603
        assert str(excinfo.value) == "Internal server error"
