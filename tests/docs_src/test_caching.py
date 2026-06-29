"""`docs/advanced/caching.md`: every claim the page makes, proved against the real SDK."""

from collections.abc import Mapping
from typing import Any, cast

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import INTERNAL_ERROR, ListToolsResult, PaginatedRequestParams, Tool

from docs_src.caching import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError
from mcp.client import CacheConfig
from mcp.client.caching import InMemoryResponseCacheStore
from mcp.server import CacheHint, MCPServer, Server, ServerRequestContext
from mcp.server.caching import CacheableMethod

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_a_mapped_method_carries_the_configured_hint() -> None:
    """tutorial001: `tools/list` is in the map, so clients see one minute, public."""
    async with Client(tutorial001.mcp) as client:
        tools = await client.list_tools()
    assert tools.ttl_ms == 60_000
    assert tools.cache_scope == "public"


async def test_a_hint_without_a_scope_stays_private() -> None:
    """tutorial001: `resources/read` set only `ttl_ms`; scope keeps the conservative default."""
    async with Client(tutorial001.mcp) as client:
        result = await client.read_resource("config://units")
    assert result.ttl_ms == 5_000
    assert result.cache_scope == "private"


async def test_an_unmapped_method_stays_immediately_stale_and_private() -> None:
    """tutorial001: `resources/list` is not in the map - the defaults hold."""
    async with Client(tutorial001.mcp) as client:
        resources = await client.list_resources()
    assert resources.ttl_ms == 0
    assert resources.cache_scope == "private"


async def test_a_non_cacheable_method_is_rejected_at_construction() -> None:
    """The page's claim: anything but the six cacheable methods raises at construction."""
    with pytest.raises(ValueError) as exc:
        MCPServer("Weather", cache_hints=cast(Any, {"tools/call": CacheHint(ttl_ms=1_000)}))
    assert str(exc.value) == snapshot(
        "cache_hints keys must be cacheable methods (see CacheableMethod); got: 'tools/call'"
    )


async def test_the_handler_value_wins_over_the_map_per_field() -> None:
    """tutorial002: the handler's `ttl_ms=1_000` beats the map's `60_000`; the scope
    the handler left unset takes the map's `"public"`."""
    async with Client(tutorial002.server) as client:
        tools = await client.list_tools()
    assert tools.ttl_ms == 1_000
    assert tools.cache_scope == "public"


async def test_the_client_program_on_the_page_makes_three_fetches_for_four_calls(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """tutorial003: a cache hit, an expiry, and `cache_mode="refresh"` make four calls cost three fetches."""
    await tutorial003.main()
    assert capsys.readouterr().out == "4 calls, 3 fetches\n"


def _counting_tools_server(*, ttl_ms: int | None = 60_000) -> tuple[Server[Any], list[str | None]]:
    """Each tools/list fetch returns a distinct tool name, so a cache hit is
    payload-distinguishable from a refetch; `ttl_ms=None` sends no hints."""
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        return ListToolsResult(tools=[Tool(name=f"t{len(fetches) - 1}", input_schema={"type": "object"})])

    hints: Mapping[CacheableMethod, CacheHint] | None = None
    if ttl_ms is not None:
        hints = {"tools/list": CacheHint(ttl_ms=ttl_ms)}
    return Server("counting", on_list_tools=list_tools, cache_hints=hints), fetches


async def test_caching_is_on_by_default_the_second_call_makes_no_fetch() -> None:
    server, fetches = _counting_tools_server()
    async with Client(server) as client:
        first = await client.list_tools()
        second = await client.list_tools()
    assert fetches == [None]
    assert second == first


async def test_a_hintless_result_is_not_cached_by_default() -> None:
    """`default_ttl_ms` defaults to 0, so a hintless server sees its usual call-for-call traffic."""
    server, fetches = _counting_tools_server(ttl_ms=None)
    async with Client(server) as client:
        await client.list_tools()
        await client.list_tools()
    assert fetches == [None, None]


async def test_cache_false_makes_every_call_a_round_trip() -> None:
    server, fetches = _counting_tools_server()
    async with Client(server, cache=False) as client:
        await client.list_tools()
        await client.list_tools()
    assert fetches == [None, None]


async def test_refresh_refetches_and_replaces_the_cached_entry() -> None:
    server, fetches = _counting_tools_server()
    async with Client(server) as client:
        await client.list_tools()
        refreshed = await client.list_tools(cache_mode="refresh")
        served = await client.list_tools()
    assert fetches == [None, None]
    assert [tool.name for tool in refreshed.tools] == ["t1"]
    assert served == refreshed


async def test_bypass_fetches_without_reading_or_writing_the_cache() -> None:
    server, fetches = _counting_tools_server()
    async with Client(server) as client:
        first = await client.list_tools()
        bypassed = await client.list_tools(cache_mode="bypass")
        served = await client.list_tools()
    assert fetches == [None, None]
    assert [tool.name for tool in bypassed.tools] == ["t1"]
    assert served == first


async def test_an_expired_entry_is_not_revived_when_the_refetch_fails() -> None:
    """SDK ruling: no stale-if-error - the refetch failure propagates."""
    now = 1_000_000.0
    fetches: list[None] = []

    async def list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(None)
        if len(fetches) > 1:
            raise MCPError(code=INTERNAL_ERROR, message="backend down")
        return ListToolsResult(tools=[Tool(name="t0", input_schema={"type": "object"})])

    server = Server("flaky", on_list_tools=list_tools, cache_hints={"tools/list": CacheHint(ttl_ms=60_000)})
    async with Client(server, cache=CacheConfig(clock=lambda: now)) as client:
        await client.list_tools()
        now += 60.0  # past the 60s TTL
        with pytest.raises(MCPError) as exc:
            await client.list_tools()
    assert exc.value.code == INTERNAL_ERROR
    assert len(fetches) == 2


async def test_two_concurrent_identical_calls_are_two_fetches() -> None:
    """SDK ruling: no coalescing. The handler barrier releases only once both
    calls are inside it, so the test passes only if the fetches were concurrent."""
    both_fetching = anyio.Event()
    fetches: list[None] = []

    async def list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(None)
        if len(fetches) == 2:
            both_fetching.set()
        with anyio.fail_after(5):
            await both_fetching.wait()
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    server = Server("concurrent", on_list_tools=list_tools, cache_hints={"tools/list": CacheHint(ttl_ms=60_000)})
    async with Client(server) as client:
        async with anyio.create_task_group() as tg:
            tg.start_soon(client.list_tools)
            tg.start_soon(client.list_tools)
    assert len(fetches) == 2


async def test_a_session_tier_call_always_makes_the_round_trip() -> None:
    """The cache lives on the `Client` verbs; `client.session` sits below it."""
    server, fetches = _counting_tools_server()
    async with Client(server) as client:
        await client.list_tools()
        await client.session.list_tools()
    assert fetches == [None, None]


async def test_a_custom_store_requires_a_partition() -> None:
    with pytest.raises(ValueError) as exc:
        CacheConfig(store=InMemoryResponseCacheStore())
    assert str(exc.value) == snapshot("a custom store requires an explicit partition")


async def test_a_custom_store_with_an_in_process_server_requires_target_id() -> None:
    server, _ = _counting_tools_server()
    with pytest.raises(ValueError) as exc:
        Client(server, cache=CacheConfig(store=InMemoryResponseCacheStore(), partition="user-1"))
    assert str(exc.value) == snapshot(
        "a custom cache store requires CacheConfig.target_id when the server is not a URL: in-process servers "
        "and Transport instances get a random per-client identity, so their entries in a shared store could "
        "never be served to another client"
    )


async def test_the_wire_presence_check_the_page_recommends_works() -> None:
    """The page's claim: `"ttl_ms" in result.model_fields_set` distinguishes a
    server that sent the field from one that said nothing (model defaults)."""
    async with Client(tutorial001.mcp) as client:
        tools = await client.list_tools()
    assert "ttl_ms" in tools.model_fields_set
