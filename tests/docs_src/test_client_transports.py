"""`docs/client/transports.md`: every claim the page makes, proved against the real SDK."""

import inspect
from typing import Any

import httpx2
import pytest

from docs_src.client_transports import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client
from mcp.client.stdio import get_default_environment
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_in_memory_program_on_the_page_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial001's `main()` is the literal client program on the page; it runs clean end to end."""
    await tutorial001.main()
    assert "Found 3 books matching 'dune'." in capsys.readouterr().out


async def test_in_memory_client_talks_to_the_server_object() -> None:
    """tutorial001: passing the server object connects in-process. No subprocess, no port."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
        assert client.protocol_version == "2026-07-28"
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result.structured_content == {"result": "Found 3 books matching 'dune'."}


async def test_constructing_a_client_does_not_connect_it() -> None:
    """tutorial002: a URL string is accepted as-is, and nothing happens until `async with`."""
    client = Client("http://localhost:8000/mcp")
    with pytest.raises(RuntimeError, match="Client must be used within an async context manager"):
        client.session


async def test_streamable_http_configuration_lives_on_the_httpx_client() -> None:
    """tutorial003: HTTP settings use `http_client=`, while SSE event size is a transport setting."""
    assert list(inspect.signature(streamable_http_client).parameters) == [
        "url",
        "http_client",
        "terminate_on_close",
        "max_sse_event_size",
    ]


async def test_the_timeout_on_the_page_is_the_sdk_clients_and_a_client_without_one_has_five_seconds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """tutorial002 and tutorial003: the `timeout=` tutorial003 passes is what `Client(url)` builds for itself
    (30 seconds, 300 for reads); an `httpx2.AsyncClient` built without one has httpx2's 5-second default."""
    async with httpx2.AsyncClient() as bare:
        assert bare.timeout == httpx2.Timeout(5.0)

    mcp = MCPServer("Bookshop")

    @mcp.tool()
    def search_books(query: str) -> str:
        """Search the catalog."""
        raise NotImplementedError

    app = mcp.streamable_http_app()
    built: list[httpx2.Timeout] = []

    class InProcessClient(httpx2.AsyncClient):
        """Every `httpx2.AsyncClient` the two programs build, routed to the server above."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx2.ASGITransport(app=app), **kwargs)
            built.append(self.timeout)

    monkeypatch.setattr(httpx2, "AsyncClient", InProcessClient)
    async with mcp.session_manager.run():
        await tutorial002.main()
        await tutorial003.main()

    assert capsys.readouterr().out == "['search_books']\n['search_books']\n"
    assert built == [httpx2.Timeout(30.0, read=300.0), httpx2.Timeout(30.0, read=300.0)]


async def test_stdio_parameters_go_straight_to_client() -> None:
    """tutorial004: `Client` takes the `StdioServerParameters` directly, and nothing is spawned until you enter it."""
    client = Client(tutorial004.server)
    with pytest.raises(RuntimeError, match="Client must be used within an async context manager"):
        client.session


async def test_the_child_environment_is_an_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """tutorial004: a variable set in the parent process is not inherited; `env=` adds it back explicitly."""
    monkeypatch.setenv("BOOKSHOP_API_KEY", "from-the-parent")
    inherited = get_default_environment()
    assert "PATH" in inherited
    assert "BOOKSHOP_API_KEY" not in inherited
    extra = tutorial004.server.env
    assert extra is not None
    assert (inherited | extra)["BOOKSHOP_API_KEY"] == "secret"
