"""Tests for the auto-derived `server/discover` handler, called directly via
`Server.get_request_handler` to isolate it from transport and dispatch."""

import importlib.metadata
from typing import Any, cast

import mcp_types as types
import pytest
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from mcp.server import Server, ServerRequestContext

# `Server._handle_discover` ignores `ctx`, so a typed None sentinel avoids dragging in session machinery.
_UNUSED_CTX = cast("ServerRequestContext[Any]", None)


async def _discover(server: Server[Any]) -> types.DiscoverResult:
    entry = server.get_request_handler("server/discover")
    assert entry is not None
    result = await entry.handler(_UNUSED_CTX, types.RequestParams())
    assert isinstance(result, types.DiscoverResult)
    return result


def test_registered_by_default() -> None:
    server = Server("test-server")
    entry = server.get_request_handler("server/discover")
    assert entry is not None
    assert entry.params_type is types.RequestParams


@pytest.mark.anyio
async def test_supported_versions_is_modern_set() -> None:
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
    result = await _discover(Server("unversioned"))
    assert result.server_info.version == importlib.metadata.version("mcp")


@pytest.mark.anyio
async def test_instructions_threaded_through() -> None:
    server = Server("inst-server", instructions="Read the docs first.")
    result = await _discover(server)
    assert result.instructions == "Read the docs first."

    bare = await _discover(Server("bare"))
    assert bare.instructions is None


@pytest.mark.anyio
async def test_capabilities_derived_from_registered_handlers() -> None:
    """Capabilities are computed at call time, so post-construction `add_request_handler` calls are reflected."""

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        raise NotImplementedError

    async def list_prompts(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        raise NotImplementedError

    server = Server("cap-server", on_list_tools=list_tools)

    before = await _discover(server)
    assert before.capabilities.tools is not None
    assert before.capabilities.prompts is None

    server.add_request_handler("prompts/list", types.PaginatedRequestParams, list_prompts)

    after = await _discover(server)
    assert after.capabilities.tools is not None
    assert after.capabilities.prompts is not None


@pytest.mark.anyio
async def test_discover_result_defaults_to_immediately_stale_private_cache() -> None:
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
