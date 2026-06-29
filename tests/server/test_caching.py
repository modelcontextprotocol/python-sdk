"""SEP-2549 caching hints: `CacheHint` validation and the `cache_hints` map reaching the wire."""

from types import UnionType
from typing import Any, cast, get_args

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CacheableResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
    Resource,
    Tool,
    methods,
)

from mcp import Client
from mcp.server import CacheHint, MCPServer, Server, ServerRequestContext
from mcp.server.caching import CACHEABLE_METHODS, apply_cache_hint

pytestmark = pytest.mark.anyio


def test_cacheable_methods_match_the_result_models() -> None:
    """Weld to the schema (SEP-2549): breaks if a result model gains or loses `CacheableResult`."""
    derived: set[str] = set()
    for method, model in methods.MONOLITH_RESULTS.items():
        arms = get_args(model) if isinstance(model, UnionType) else (model,)
        if any(isinstance(arm, type) and issubclass(arm, CacheableResult) for arm in arms):
            derived.add(method)
    assert CACHEABLE_METHODS == derived


def test_cache_hint_defaults_match_the_conservative_model_defaults() -> None:
    """An unconfigured hint fills what the models already default to, so stamping it is a no-op."""
    hint = CacheHint()
    model = ListToolsResult(tools=[])
    assert (hint.ttl_ms, hint.scope) == (model.ttl_ms, model.cache_scope)


def test_a_negative_ttl_is_rejected_at_hint_construction() -> None:
    """Spec: servers MUST provide `ttlMs >= 0`."""
    with pytest.raises(ValueError) as exc:
        CacheHint(ttl_ms=-1)
    assert str(exc.value) == snapshot("ttl_ms must be >= 0, got -1")


def test_an_unknown_scope_is_rejected_at_hint_construction() -> None:
    """`cacheScope` is a closed enum; the runtime check covers callers the type checker cannot see."""
    with pytest.raises(ValueError) as exc:
        CacheHint(scope=cast(Any, "shared"))
    assert str(exc.value) == snapshot("scope must be 'public' or 'private', got 'shared'")


def test_apply_cache_hint_fills_only_the_fields_the_handler_left_unset() -> None:
    result = ListToolsResult(tools=[], ttl_ms=10)
    filled = apply_cache_hint(result, CacheHint(ttl_ms=60_000, scope="public"))
    assert filled.ttl_ms == 10
    assert filled.cache_scope == "public"


def test_apply_cache_hint_never_overrides_explicit_fields_even_at_default_values() -> None:
    """`model_fields_set` distinguishes an explicit default from an unset field."""
    result = ListToolsResult(tools=[], ttl_ms=0, cache_scope="private")
    assert apply_cache_hint(result, CacheHint(ttl_ms=60_000, scope="public")) is result


def test_a_non_cacheable_method_in_cache_hints_is_rejected_at_server_construction() -> None:
    with pytest.raises(ValueError) as exc:
        Server("srv", cache_hints=cast(Any, {"tools/call": CacheHint()}))
    assert str(exc.value) == snapshot(
        "cache_hints keys must be cacheable methods (see CacheableMethod); got: tools/call"
    )


def test_a_non_cache_hint_value_is_rejected_at_server_construction() -> None:
    with pytest.raises(TypeError) as exc:
        Server("srv", cache_hints=cast(Any, {"tools/list": {"ttl_ms": 60_000}}))
    assert str(exc.value) == snapshot("cache_hints['tools/list'] must be a CacheHint, got dict")


async def test_server_cache_hints_reach_the_wire_for_a_bare_handler_result() -> None:
    hint = CacheHint(ttl_ms=60_000, scope="public")

    async def list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    server = Server("srv", on_list_tools=list_tools, cache_hints={"tools/list": hint})
    async with Client(server) as client:
        result = await client.list_tools()
    assert result.ttl_ms == hint.ttl_ms
    assert result.cache_scope == hint.scope


async def test_every_page_of_a_paginated_list_carries_the_configured_scope() -> None:
    """Spec: one list's pages MUST share a `cacheScope`. The map is keyed by method, not cursor;
    a handler that overrides the scope owns that consistency itself (see `docs/advanced/caching.md`)."""
    names = [f"r-{n}" for n in range(4)]

    async def list_resources(
        ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        start = 0 if params is None or params.cursor is None else int(params.cursor)
        page = [Resource(uri=f"res://{name}", name=name) for name in names[start : start + 2]]
        next_cursor = str(start + 2) if start + 2 < len(names) else None
        return ListResourcesResult(resources=page, next_cursor=next_cursor)

    server = Server(
        "srv",
        on_list_resources=list_resources,
        cache_hints={"resources/list": CacheHint(ttl_ms=30_000, scope="public")},
    )
    async with Client(server) as client:
        first = await client.list_resources()
        assert first.next_cursor is not None
        second = await client.list_resources(cursor=first.next_cursor)
    assert (first.cache_scope, second.cache_scope) == ("public", "public")
    assert (first.ttl_ms, second.ttl_ms) == (30_000, 30_000)


async def test_the_default_discover_handler_takes_the_server_discover_hint() -> None:
    server = Server("srv", cache_hints={"server/discover": CacheHint(ttl_ms=300_000, scope="public")})
    async with Client(server) as client:
        discovered = await client.session.discover()
    assert discovered.ttl_ms == 300_000
    assert discovered.cache_scope == "public"


async def test_mcpserver_cache_hints_cover_every_high_level_handler() -> None:
    """Distinct `ttl_ms` per method so a failure names the handler that lost its hint."""
    mcp = MCPServer(
        "demo",
        cache_hints={
            "tools/list": CacheHint(ttl_ms=1_000, scope="public"),
            "resources/list": CacheHint(ttl_ms=2_000, scope="public"),
            "resources/templates/list": CacheHint(ttl_ms=3_000, scope="public"),
            "prompts/list": CacheHint(ttl_ms=4_000, scope="public"),
            "resources/read": CacheHint(ttl_ms=5_000, scope="public"),
            "server/discover": CacheHint(ttl_ms=6_000, scope="public"),
        },
    )

    @mcp.tool()
    def add(a: int, b: int) -> int:
        raise NotImplementedError

    @mcp.resource("config://app")
    def config() -> str:
        return "cfg"

    @mcp.resource("greeting://{name}")
    def greeting(name: str) -> str:
        raise NotImplementedError

    @mcp.prompt()
    def hello() -> str:
        raise NotImplementedError

    async with Client(mcp) as client:
        assert (await client.list_tools()).ttl_ms == 1_000
        assert (await client.list_resources()).ttl_ms == 2_000
        assert (await client.list_resource_templates()).ttl_ms == 3_000
        assert (await client.list_prompts()).ttl_ms == 4_000
        assert (await client.read_resource("config://app")).ttl_ms == 5_000
        assert (await client.session.discover()).ttl_ms == 6_000
