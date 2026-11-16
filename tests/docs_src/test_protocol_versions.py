"""`docs/protocol-versions.md`: every claim the page makes, proved against the real SDK.

The page's snippets are URL clients for the Bookshop `server.py` from The Client page
(`docs_src/client/tutorial001.py`). These tests open the same connections in-process
against that server object, so each `mode=` is exercised without a port.
"""

import re

import pytest
from mcp_types import SERVER_INFO_META_KEY, DiscoverResult, Implementation, ServerCapabilities

from docs_src.client import tutorial001 as bookshop
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_auto_lands_on_the_modern_version() -> None:
    """tutorial001's connection, in-process: the default `mode="auto"` probes `server/discover`
    and adopts the result, so the page's `2026-07-28` output block is what it prints."""
    async with Client(bookshop.mcp) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
        assert client.session.discover_result is not None
        assert client.session.initialize_result is None


async def test_legacy_forces_the_initialize_handshake() -> None:
    """tutorial002's connection, in-process: `mode="legacy"` runs `initialize` against the very
    same server and lands on the newest handshake-era version."""
    async with Client(bookshop.mcp, mode="legacy") as client:
        assert client.protocol_version == "2025-11-25"
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
        assert client.session.initialize_result is not None
        assert client.session.discover_result is None


async def test_version_pin_sends_nothing_and_knows_nothing() -> None:
    """tutorial003's connection, in-process: a pin adopts the version locally, so `server_info`
    is None and every capability is blank, yet a tool call still round-trips."""
    async with Client(bookshop.mcp, mode="2026-07-28") as client:
        assert client.protocol_version == "2026-07-28"
        assert client.session.initialize_result is None
        # The `!!! check` fence is the literal `print(client.server_info)` output: None.
        assert client.server_info is None
        assert client.server_capabilities == ServerCapabilities()
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result.structured_content == {"result": "Found 3 books matching 'dune' (showing up to 10)."}


def test_handshake_era_version_is_not_a_valid_pin() -> None:
    """A pre-2026 version string is rejected at construction with the exact error the page shows."""
    with pytest.raises(
        ValueError,
        match=re.escape(
            "mode must be 'legacy', 'auto', or one of ['2026-07-28']; "
            "got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')"
        ),
    ):
        Client(bookshop.mcp, mode="2025-06-18")


async def test_prior_discover_round_trips() -> None:
    """tutorial004's flow, driven in-process against the Bookshop server: save `discover_result`,
    reconnect pinned with it, and the identity comes back without any negotiation."""
    async with Client(bookshop.mcp) as client:
        saved = client.session.discover_result
    assert saved is not None
    assert saved.supported_versions == ["2026-07-28"]

    async with Client(bookshop.mcp, mode="2026-07-28", prior_discover=saved) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.session.discover_result is saved
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
        assert client.server_capabilities.tools is not None


async def test_discover_result_survives_json() -> None:
    """`DiscoverResult` is a Pydantic model: dump it to JSON, validate it back, reconnect with it."""
    async with Client(bookshop.mcp) as client:
        saved = client.session.discover_result
    assert saved is not None

    restored = DiscoverResult.model_validate_json(saved.model_dump_json())
    assert restored == saved

    async with Client(bookshop.mcp, mode="2026-07-28", prior_discover=restored) as client:
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"


async def test_prior_discover_is_ignored_unless_mode_is_a_pin() -> None:
    """The `!!! tip`: under `auto` the client probes anyway; under `legacy` it never discovers."""
    stale = DiscoverResult(
        supported_versions=["2026-07-28"],
        capabilities=ServerCapabilities(),
        _meta={
            SERVER_INFO_META_KEY: Implementation(name="Stale", version="0.0.0").model_dump(
                by_alias=True, mode="json", exclude_none=True
            )
        },
    )
    async with Client(bookshop.mcp, prior_discover=stale) as client:
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
    async with Client(bookshop.mcp, mode="legacy", prior_discover=stale) as client:
        assert client.session.discover_result is None
        assert client.protocol_version == "2025-11-25"
