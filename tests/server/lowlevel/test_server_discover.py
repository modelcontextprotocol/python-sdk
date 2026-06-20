"""Direct-handler tests for the auto-derived `server/discover` handler.

These call the registered handler straight from `Server._request_handlers`
without spinning up a `ServerRunner` or any transport, so they verify the
handler's contract in isolation from the dispatch pipeline.
"""

from typing import Any, cast

import pytest

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.shared.version import MODERN_PROTOCOL_VERSIONS

# The default handler ignores its `ctx` argument entirely (it derives the
# result from server state), so a sentinel keeps the call site type-correct
# without dragging session machinery into a unit test.
_UNUSED_CTX = cast("ServerRequestContext[Any]", None)


async def _discover(server: Server[Any]) -> types.DiscoverResult:
    entry = server._request_handlers["server/discover"]
    result = await entry.handler(_UNUSED_CTX, types.RequestParams())
    assert isinstance(result, types.DiscoverResult)
    return result


def test_registered_by_default() -> None:
    server = Server("test-server")
    assert "server/discover" in server._request_handlers
    entry = server._request_handlers["server/discover"]
    assert entry.params_type is types.RequestParams


@pytest.mark.anyio
async def test_supported_versions_is_modern_set() -> None:
    """`supportedVersions` is exactly the modern envelope set, not the full
    legacy-compat list (D-008)."""
    result = await _discover(Server("test-server"))
    assert result.supported_versions == list(MODERN_PROTOCOL_VERSIONS)


@pytest.mark.anyio
async def test_server_info_reflects_constructor_fields() -> None:
    icons = [types.Icon(src="https://example.test/icon.png")]
    server = Server(
        "info-server",
        version="9.9.9",
        title="Info Server",
        description="A server for testing discover.",
        website_url="https://example.test",
        icons=icons,
    )
    result = await _discover(server)
    assert result.server_info == types.Implementation(
        name="info-server",
        version="9.9.9",
        title="Info Server",
        description="A server for testing discover.",
        website_url="https://example.test",
        icons=icons,
    )


@pytest.mark.anyio
async def test_server_info_version_falls_back_to_package() -> None:
    """When no explicit version is supplied, `serverInfo.version` is still a
    non-empty string (the installed `mcp` package version)."""
    result = await _discover(Server("unversioned"))
    assert isinstance(result.server_info.version, str)
    assert result.server_info.version


@pytest.mark.anyio
async def test_instructions_threaded_through() -> None:
    server = Server("inst-server", instructions="Read the docs first.")
    result = await _discover(server)
    assert result.instructions == "Read the docs first."

    bare = await _discover(Server("bare"))
    assert bare.instructions is None


@pytest.mark.anyio
async def test_capabilities_derived_from_registered_handlers() -> None:
    """Capabilities are computed at handler call time from the live registry,
    so post-construction `add_request_handler` calls are reflected."""

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    async def list_prompts(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    server = Server("cap-server", on_list_tools=list_tools)

    before = await _discover(server)
    assert before.capabilities.tools is not None
    assert before.capabilities.prompts is None

    server.add_request_handler("prompts/list", types.PaginatedRequestParams, list_prompts)

    after = await _discover(server)
    assert after.capabilities.tools is not None
    assert after.capabilities.prompts is not None


@pytest.mark.anyio
async def test_cacheable_defaults() -> None:
    """`DiscoverResult` is cacheable; the auto-derived handler relies on the
    model defaults (immediately-stale, private)."""
    result = await _discover(Server("cache-server"))
    assert result.ttl_ms == 0
    assert result.cache_scope == "private"


@pytest.mark.anyio
async def test_overridable_via_add_request_handler() -> None:
    server = Server("custom-server", version="1.0.0")
    custom = types.DiscoverResult(
        supported_versions=list(MODERN_PROTOCOL_VERSIONS),
        capabilities=types.ServerCapabilities(),
        server_info=types.Implementation(name="custom-server", version="1.0.0"),
        instructions="overridden",
        ttl_ms=60_000,
        cache_scope="public",
    )

    async def custom_discover(
        ctx: ServerRequestContext[Any], params: types.RequestParams | None
    ) -> types.DiscoverResult:
        return custom

    server.add_request_handler("server/discover", types.RequestParams, custom_discover)
    result = await _discover(server)
    assert result is custom
