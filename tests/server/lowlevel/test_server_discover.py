"""Direct-handler tests for the auto-derived `server/discover` handler.

These call the registered handler via the public `Server.get_request_handler`
accessor without spinning up a `ServerRunner` or any transport, so they verify
the handler's contract in isolation from the dispatch pipeline.
"""

import importlib.metadata
from typing import Any, cast

import mcp_types as types
import pytest
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from mcp.server import NotificationOptions, Server, ServerRequestContext


# `Server._handle_discover` reads only `ctx.protocol_version` (capabilities are
# era-dependent), so a minimal context keeps the call site honest without
# dragging session machinery into a unit test.
def _ctx(protocol_version: str) -> ServerRequestContext[Any]:
    return ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version=protocol_version,
        method="server/discover",
        request_id=1,
    )


async def _discover(server: Server[Any], protocol_version: str = MODERN_PROTOCOL_VERSIONS[0]) -> types.DiscoverResult:
    entry = server.get_request_handler("server/discover")
    assert entry is not None
    result = await entry.handler(_ctx(protocol_version), types.RequestParams())
    assert isinstance(result, types.DiscoverResult)
    return result


def test_registered_by_default() -> None:
    """SDK-defined: a bare `Server` registers a `server/discover` handler out of
    the box, typed for the base `RequestParams`."""
    server = Server("test-server")
    entry = server.get_request_handler("server/discover")
    assert entry is not None
    assert entry.params_type is types.RequestParams


@pytest.mark.anyio
async def test_supported_versions_is_modern_set() -> None:
    """`supportedVersions` is exactly the modern envelope set, not the full
    legacy-compat list (D-008)."""
    result = await _discover(Server("test-server"))
    assert result.supported_versions == list(MODERN_PROTOCOL_VERSIONS)


@pytest.mark.anyio
async def test_server_info_reflects_constructor_fields() -> None:
    """SDK-defined: `serverInfo` is built field-for-field from the `Server`
    constructor arguments."""
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
    """SDK-defined: when no explicit version is supplied, `serverInfo.version`
    falls back to the installed `mcp` package version."""
    result = await _discover(Server("unversioned"))
    assert result.server_info.version == importlib.metadata.version("mcp")


@pytest.mark.anyio
async def test_instructions_threaded_through() -> None:
    """SDK-defined: the `instructions` constructor argument is passed through
    verbatim, defaulting to `None` when omitted."""
    server = Server("inst-server", instructions="Read the docs first.")
    result = await _discover(server)
    assert result.instructions == "Read the docs first."

    bare = await _discover(Server("bare"))
    assert bare.instructions is None


@pytest.mark.anyio
async def test_capabilities_derived_from_registered_handlers() -> None:
    """SDK-defined: capabilities are computed at handler call time from the
    live registry, so post-construction `add_request_handler` calls are
    reflected."""

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
    """SDK-defined: `DiscoverResult` is cacheable; the auto-derived handler
    relies on the model defaults (immediately-stale, private)."""
    result = await _discover(Server("cache-server"))
    assert result.ttl_ms == 0
    assert result.cache_scope == "private"


@pytest.mark.anyio
async def test_overridable_via_add_request_handler() -> None:
    """SDK-defined: a custom `server/discover` handler registered via
    `add_request_handler` replaces the auto-derived default wholesale."""
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


async def _listen_stub(
    ctx: ServerRequestContext[Any], params: types.SubscriptionsListenRequestParams
) -> types.SubscriptionsListenResult:
    raise NotImplementedError


@pytest.mark.anyio
async def test_modern_subscription_bits_derive_from_listen_serving() -> None:
    """Spec-driven (SEP-2575): at 2026-07-28, change notifications exist only on
    `subscriptions/listen` streams, so the `listChanged`/`subscribe` bits mean
    "this server serves listen" - they flip together with the handler."""

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        raise NotImplementedError

    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        raise NotImplementedError

    server = Server("caps", on_list_tools=list_tools, on_list_resources=list_resources)

    before = await _discover(server)
    assert before.capabilities.tools is not None and before.capabilities.tools.list_changed is False
    assert before.capabilities.resources is not None
    assert before.capabilities.resources.subscribe is False
    assert before.capabilities.resources.list_changed is False

    server.add_request_handler("subscriptions/listen", types.SubscriptionsListenRequestParams, _listen_stub)

    after = await _discover(server)
    assert after.capabilities.tools is not None and after.capabilities.tools.list_changed is True
    assert after.capabilities.resources is not None
    assert after.capabilities.resources.subscribe is True
    assert after.capabilities.resources.list_changed is True


@pytest.mark.anyio
async def test_legacy_capability_derivation_ignores_listen() -> None:
    """SDK-defined: without `protocol_version`, `get_capabilities` keeps the
    handshake-era derivation - `NotificationOptions` drives `listChanged` and the
    `resources/subscribe` handler drives `subscribe`; a registered listen handler
    changes nothing on that path."""

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        raise NotImplementedError

    server = Server("caps", on_list_tools=list_tools)
    server.add_request_handler("subscriptions/listen", types.SubscriptionsListenRequestParams, _listen_stub)

    legacy = server.get_capabilities()
    assert legacy.tools is not None and legacy.tools.list_changed is False

    opted_in = server.get_capabilities(NotificationOptions(tools_changed=True))
    assert opted_in.tools is not None and opted_in.tools.list_changed is True
