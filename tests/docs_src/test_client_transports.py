"""`docs/client/transports.md`: every claim the page makes, proved against the real SDK."""

import inspect

import pytest

from docs_src.client_transports import tutorial001, tutorial004
from mcp import Client
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_in_memory_program_on_the_page_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial001's `main()` is the literal client program on the page; it runs clean end to end."""
    await tutorial001.main()
    assert "Found 3 books matching 'dune'." in capsys.readouterr().out


async def test_in_memory_client_talks_to_the_server_object() -> None:
    """tutorial001: passing the server object connects in-process. No subprocess, no port."""
    async with Client(tutorial001.mcp) as client:
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
    """tutorial003: `streamable_http_client` takes `http_client=`; there is no `headers=` or any other HTTP knob."""
    assert list(inspect.signature(streamable_http_client).parameters) == ["url", "http_client", "terminate_on_close"]


async def test_stdio_parameters_are_wrapped_by_stdio_client() -> None:
    """tutorial004: `stdio_client(params)` is the transport, and `Client` takes it like any other."""
    client = Client(stdio_client(tutorial004.server))
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
