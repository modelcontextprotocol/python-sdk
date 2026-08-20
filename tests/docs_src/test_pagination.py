"""`docs/advanced/pagination.md`: every claim the page makes, proved against the real SDK."""

import pytest
from mcp_types import Resource

from docs_src.pagination import tutorial001, tutorial002, tutorial003
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


async def test_the_loop_collects_all_one_hundred() -> None:
    """tutorial001: the `cursor=` loop visits ten pages and reassembles the whole catalog."""
    async with Client(tutorial001.server) as client:
        resources: list[Resource] = []
        cursor: str | None = None
        pages = 0
        while True:
            page = await client.list_resources(cursor=cursor)
            resources.extend(page.resources)
            pages += 1
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert pages == 10
        assert len({resource.uri for resource in resources}) == 100


async def test_the_client_program_on_the_page_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial002: `main()` is the literal client program on the page and prints the stitched total."""
    await tutorial002.main()
    assert capsys.readouterr().out == "100 resources\n"


async def test_list_all_stitches_the_whole_catalog() -> None:
    """tutorial003: `list_all_resources` drains every page into one list, no cursor handling."""
    async with Client(tutorial003.server) as client:
        resources = await client.list_all_resources()
        assert len(resources) == 100
        assert resources[0].name == "book-1"
        assert resources[-1].name == "book-100"


async def test_the_drain_helpers_program_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial003: `main()` stitches all pages, then streams and stops at the first."""
    await tutorial003.main()
    assert capsys.readouterr().out == "100 resources\nfirst: book-1\n"


async def test_an_invented_cursor_is_an_error() -> None:
    """Cursors are opaque: a string the server never minted blows up inside the handler."""
    async with Client(tutorial001.server) as client:
        with pytest.raises(MCPError) as excinfo:
            await client.list_resources(cursor="page-2")
        assert excinfo.value.code == -32603
        assert str(excinfo.value) == "Internal server error"
