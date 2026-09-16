"""SEP-2549 caching hints: handler-authored TTL/scope hints and the defaults a client sees without them."""

import mcp_types as types
import pytest
from mcp_types import (
    ListPromptsResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    Prompt,
    ResourceTemplate,
    Tool,
)

from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

# Non-default values (the defaults are 0/"private") prove the authored hints travelled.
PROMPTS_TTL_MS = 60_000
TEMPLATES_TTL_MS = 120_000


@requirement("caching:hints:prompts-list")
async def test_prompts_list_result_carries_the_handler_authored_ttl_and_scope_hints(connect: Connect) -> None:
    """Handler-authored ttlMs/cacheScope on a prompts/list result reach the client unmodified. Spec-mandated."""

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        assert params is not None
        return ListPromptsResult(prompts=[Prompt(name="greet")], ttl_ms=PROMPTS_TTL_MS, cache_scope="public")

    server = Server("cached", on_list_prompts=list_prompts)

    async with connect(server) as client:
        result = await client.list_prompts()

    assert result.ttl_ms == PROMPTS_TTL_MS
    assert result.cache_scope == "public"
    assert result.result_type == "complete"
    assert result.prompts == [Prompt(name="greet")]


@requirement("caching:hints:resources-templates-list")
async def test_resource_templates_list_result_carries_the_handler_authored_ttl_and_scope_hints(
    connect: Connect,
) -> None:
    """Handler-authored hints on a resources/templates/list result reach the client unmodified. Spec-mandated."""

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        assert params is not None
        return ListResourceTemplatesResult(
            resource_templates=[ResourceTemplate(name="file", uri_template="file:///{name}")],
            ttl_ms=TEMPLATES_TTL_MS,
            cache_scope="public",
        )

    server = Server("cached", on_list_resource_templates=list_resource_templates)

    async with connect(server) as client:
        result = await client.list_resource_templates()

    assert result.ttl_ms == TEMPLATES_TTL_MS
    assert result.cache_scope == "public"
    assert result.result_type == "complete"
    assert result.resource_templates == [ResourceTemplate(name="file", uri_template="file:///{name}")]


@requirement("caching:pagination:same-scope-all-pages")
async def test_mismatched_per_page_cache_scopes_are_forwarded_unmodified_across_a_cursor_walk(
    connect: Connect,
) -> None:
    """Mismatched per-page cacheScopes in one cursor walk reach the client unmodified (pinned Divergence).

    When enforcement lands: re-pin to `page2.cache_scope == page1.cache_scope` and delete the Divergence.
    """
    seen_cursors: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListToolsResult(
                tools=[Tool(name="a", input_schema={"type": "object"})],
                next_cursor="page-2",
                cache_scope="public",
            )
        assert params.cursor == "page-2"
        # Deliberately mismatched with page 1's "public": the forwarded mismatch is the pinned gap.
        return ListToolsResult(tools=[Tool(name="b", input_schema={"type": "object"})], cache_scope="private")

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        page1 = await client.list_tools()
        page2 = await client.list_tools(cursor=page1.next_cursor)

    assert page1.cache_scope == "public"
    assert page2.cache_scope == "private"
    assert seen_cursors == [None, "page-2"]


@requirement("caching:ttl:absent-defaults-zero")
async def test_a_result_without_ttl_from_a_2025_server_surfaces_the_immediately_stale_defaults(
    connect: Connect,
) -> None:
    """A hint-less 2025-era result surfaces ttl_ms 0 (immediately stale) and cache_scope private.

    The ttl half is the spec SHOULD for older servers; the private half is SDK-defined behaviour.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        # Neither hint authored: the spec's "older server versions" scenario.
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        result = await client.list_tools()

    assert result.ttl_ms == 0
    assert result.cache_scope == "private"
    assert [tool.name for tool in result.tools] == ["t"]


@requirement("caching:ttl:zero-immediately-stale")
async def test_ttl_zero_results_are_refetched_on_every_access(connect: Connect) -> None:
    """Two consecutive list_tools calls against a ttlMs-0 server both reach the handler.

    Load-bearing against the live response cache: a ttlMs-0 result is never stored, so every
    access re-fetches, while the same seam with a positive ttl_ms serves the second access from
    cache (one fetch).
    """
    fetches: list[int] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        fetches.append(1)
        # Explicit ttl_ms=0: the value under test, not the default's accident.
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})], ttl_ms=0, cache_scope="public")

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        first = await client.list_tools()
        second = await client.list_tools()

    assert len(fetches) == 2
    assert first.ttl_ms == 0
    assert second.ttl_ms == 0
