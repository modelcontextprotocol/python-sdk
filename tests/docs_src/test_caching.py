"""`docs/advanced/caching.md`: every claim the page makes, proved against the real SDK."""

from typing import Any, cast

import pytest
from inline_snapshot import snapshot

from docs_src.caching import tutorial001, tutorial002, tutorial003
from mcp import Client
from mcp.server import CacheHint, MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_a_mapped_method_carries_the_configured_hint() -> None:
    async with Client(tutorial001.mcp) as client:
        tools = await client.list_tools()
    assert tools.ttl_ms == 60_000
    assert tools.cache_scope == "public"


async def test_a_hint_without_a_scope_stays_private() -> None:
    async with Client(tutorial001.mcp) as client:
        result = await client.read_resource("config://units")
    assert result.ttl_ms == 5_000
    assert result.cache_scope == "private"


async def test_an_unmapped_method_stays_immediately_stale_and_private() -> None:
    async with Client(tutorial001.mcp) as client:
        resources = await client.list_resources()
    assert resources.ttl_ms == 0
    assert resources.cache_scope == "private"


async def test_a_non_cacheable_method_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError) as exc:
        MCPServer("Weather", cache_hints=cast(Any, {"tools/call": CacheHint(ttl_ms=1_000)}))
    assert str(exc.value) == snapshot(
        "cache_hints keys must be cacheable methods (see CacheableMethod); got: tools/call"
    )


async def test_the_handler_value_wins_over_the_map_per_field() -> None:
    """tutorial002's map sets `ttl_ms=60_000, scope="public"`; the handler overrides only `ttl_ms`."""
    async with Client(tutorial002.server) as client:
        tools = await client.list_tools()
    assert tools.ttl_ms == 1_000
    assert tools.cache_scope == "public"


async def test_the_client_program_on_the_page_reads_the_hints(capsys: pytest.CaptureFixture[str]) -> None:
    await tutorial003.main()
    assert capsys.readouterr().out == "1 tools, fresh for 60s, scope=public\n"


async def test_the_wire_presence_check_the_page_recommends_works() -> None:
    """Presence in `model_fields_set` proves the server sent the field rather than the model defaulting it."""
    async with Client(tutorial003.mcp) as client:
        tools = await client.list_tools()
    assert "ttl_ms" in tools.model_fields_set
