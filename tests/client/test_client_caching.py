"""`Client` wiring for the response cache: the `cache=` constructor kwarg, server
identity resolution (explicit `target_id`, URL, per-client random), the custom-store
identity guard, the notification-eviction message-handler wrap, the lazy
negotiated-version supplier, and the five cacheable verbs (the `_cached_fetch`
choke point, the `read_resource` sibling, and the tools/list absorption seam).
Cross-cutting end-to-end hardening (eviction completeness, partition isolation,
deep-copy isolation, era-gate injection, write/eviction races) lives at the
bottom. The coordinator's own behavior is covered in `test_caching.py`.
"""

import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Literal

import anyio
import anyio.lowlevel
import httpx
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CallToolResult,
    DiscoverResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    Implementation,
    InputRequiredResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    ReadResourceResult,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    ServerCapabilities,
    ServerNotification,
    TextContent,
    TextResourceContents,
    Tool,
    ToolListChangedNotification,
)
from mcp_types.version import LATEST_MODERN_VERSION

from mcp.client import Client
from mcp.client._transport import TransportStreams
from mcp.client.caching import (
    CacheConfig,
    CacheEntry,
    CacheKey,
    ClientResponseCache,
    InMemoryResponseCacheStore,
)
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.caching import CacheHint
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from tests.interaction._connect import BASE_URL, mounted_app

pytestmark = pytest.mark.anyio

IncomingMessage = RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception


def _coordinator(client: Client) -> ClientResponseCache:
    cache = client._response_cache
    assert cache is not None
    return cache


def _private_arm(client: Client) -> str:
    """The arm string the coordinator stamps into every store key's partition field.

    Server identity is only observable through it pre-verbs; `test_caching.py` pins
    the arm layout, so only equality between clients matters here.
    """
    return _coordinator(client)._private_arm


def _tools_list_key(client: Client) -> CacheKey:
    return CacheKey("tools/list", "", _private_arm(client))


class _OpaqueTransport:
    """Shape-only `Transport`: identity resolution happens at construction, so the
    tests never enter it."""

    async def __aenter__(self) -> TransportStreams:
        raise NotImplementedError

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        raise NotImplementedError


def _list_changed_server() -> Server[Any]:
    """In-process server whose `touch` tool emits `notifications/tools/list_changed`.

    The notification-delivery tests connect with `mode="legacy"`: the modern
    in-process DirectDispatcher path has no standalone channel and drops unrelated
    server notifications before they reach the client, so the legacy in-memory
    stream pair is the lightest transport that actually delivers them.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[types.Tool(name="touch", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "touch"
        await ctx.session.send_tool_list_changed()
        return CallToolResult(content=[TextContent(text="touched")])

    return Server("notifier", on_list_tools=list_tools, on_call_tool=call_tool)


async def _warm_tools_list_entry(client: Client) -> CacheKey:
    """Seed a private-arm tools/list entry directly in the client's store; eviction
    deletes regardless of freshness, so the entry's payload and expiry are inert."""
    key = _tools_list_key(client)
    await _coordinator(client)._store.set(key, CacheEntry(value="warm", scope="private", expires_at=None))
    return key


def test_an_explicit_target_id_overrides_both_url_and_in_process_identity() -> None:
    """`CacheConfig.target_id` wins over every server shape: a URL client and an
    in-process client given the same target_id share one cache identity, distinct
    from the URL-derived one. SDK-defined resolution order."""
    by_target_url = Client("https://example.com/mcp", cache=CacheConfig(target_id="svc"))
    by_target_inproc = Client(Server("plain"), cache=CacheConfig(target_id="svc"))
    by_url = Client("https://example.com/mcp")

    assert _private_arm(by_target_url) == _private_arm(by_target_inproc)
    assert _private_arm(by_target_url) != _private_arm(by_url)


def test_userinfo_variants_of_a_server_url_share_one_cache_identity() -> None:
    """Stripping credentials is the single permitted URL rewrite: userinfo variants
    of the same URL resolve to the identity of the bare URL. SDK-defined."""
    bare = Client("https://example.com/mcp")
    with_password = Client("https://user:secret@example.com/mcp")
    with_token = Client("https://token@example.com/mcp")

    assert _private_arm(bare) == _private_arm(with_password) == _private_arm(with_token)


def test_the_server_url_is_sha256_hashed_before_it_enters_key_material() -> None:
    """The arm carries sha256(url-sans-userinfo), not the URL itself, so a secret
    in the query string never appears in store keys. SDK-defined; pins the docs'
    secrets-never-in-keys claim — raw-URL key material would fail here."""
    client = Client("https://user:pass@example.com/mcp?api_key=SECRET")

    arm_id = hashlib.sha256(b"https://example.com/mcp?api_key=SECRET").hexdigest()
    assert _private_arm(client) == json.dumps(["private", arm_id, ""])


def test_urls_differing_only_in_query_have_distinct_cache_identities() -> None:
    """URL identity is byte-exact outside userinfo — `?tenant=a` and `?tenant=b`
    must never share entries (over-normalization would merge tenants). SDK-defined."""
    tenant_a = Client("https://example.com/mcp?tenant=a")
    tenant_b = Client("https://example.com/mcp?tenant=b")

    assert _private_arm(tenant_a) != _private_arm(tenant_b)


def test_two_clients_on_one_in_process_server_get_distinct_cache_identities() -> None:
    """An in-process server has no URL, so each client gets a random per-client
    identity — two clients on the same server never share entries. SDK-defined."""
    server = Server("plain")

    assert _private_arm(Client(server)) != _private_arm(Client(server))


def test_a_transport_object_gets_a_per_client_cache_identity() -> None:
    """The `Transport` protocol carries no URL, so a transport-backed client gets
    the same random per-client identity as an in-process one. SDK-defined."""
    transport = _OpaqueTransport()

    assert _private_arm(Client(transport)) != _private_arm(Client(transport))


@pytest.mark.parametrize("make_server", [lambda: Server("plain"), _OpaqueTransport], ids=["in-process", "transport"])
def test_a_custom_store_without_a_url_or_target_id_is_rejected(make_server: Any) -> None:
    """A shared store keyed by a random per-client identity would accumulate entries
    no other client can ever read, so construction refuses the combination and
    points at the fix."""
    with pytest.raises(ValueError) as exc_info:
        Client(make_server(), cache=CacheConfig(store=InMemoryResponseCacheStore(), partition="p"))
    assert str(exc_info.value) == snapshot(
        "a custom cache store requires CacheConfig.target_id when the server is not a URL: in-process servers "
        "and Transport instances get a random per-client identity, so their entries in a shared store could "
        "never be served to another client"
    )


def test_a_custom_store_with_a_url_server_constructs_and_is_used() -> None:
    """A URL provides a stable identity, so a custom store needs no `target_id`."""
    store = InMemoryResponseCacheStore()
    client = Client("https://example.com/mcp", cache=CacheConfig(store=store, partition="p"))

    assert _coordinator(client)._store is store


def test_a_custom_store_with_an_explicit_target_id_constructs_for_any_server() -> None:
    """`target_id` is the documented escape hatch: it lifts the custom-store guard
    even for an in-process server."""
    store = InMemoryResponseCacheStore()
    client = Client(Server("plain"), cache=CacheConfig(store=store, partition="p", target_id="svc"))

    assert _coordinator(client)._store is store


async def test_cache_false_disables_the_cache_and_the_handler_wrap() -> None:
    """`cache=False` mints no coordinator and installs the user's handler unwrapped —
    today's no-cache behavior exactly."""

    async def handler(message: IncomingMessage) -> None:
        raise NotImplementedError

    client = Client(_list_changed_server(), cache=False, message_handler=handler)
    assert client._response_cache is None

    async with client:
        assert client.session._message_handler is handler


def test_the_default_cache_uses_a_per_client_in_memory_store() -> None:
    """`cache=None` (the default) is cache-on: each client gets its own coordinator
    backed by its own in-memory store, never shared between clients."""
    server = Server("plain")
    first = Client(server)
    second = Client(server)

    assert isinstance(_coordinator(first)._store, InMemoryResponseCacheStore)
    assert _coordinator(first)._store is not _coordinator(second)._store


async def test_the_negotiated_version_supplier_tracks_the_session_lifecycle() -> None:
    """The era supplier returns None before connect (and again after exit) and the
    negotiated version while the session is live — the era gate must never read a
    stale or raising source."""
    client = Client(_list_changed_server())
    supplier = _coordinator(client)._negotiated_version

    assert supplier() is None
    async with client:
        assert supplier() == client.protocol_version
    assert supplier() is None


async def test_a_list_changed_notification_evicts_without_a_user_handler() -> None:
    """With no user handler the wrap is still installed: a tools/list_changed
    notification deletes the warm tools/list entry from both arms. Spec SHOULD
    (notifications invalidate)."""

    class _EventedStore(InMemoryResponseCacheStore):
        """Signals once both arms of an eviction have been deleted."""

        def __init__(self) -> None:
            super().__init__()
            self._deletes = 0
            self.both_arms_deleted = anyio.Event()

        async def delete(self, key: CacheKey) -> None:
            await super().delete(key)
            self._deletes += 1
            if self._deletes == 2:
                self.both_arms_deleted.set()

    store = _EventedStore()
    client = Client(
        _list_changed_server(), mode="legacy", cache=CacheConfig(store=store, partition="p", target_id="svc")
    )

    async with client:
        key = await _warm_tools_list_entry(client)
        await client.call_tool("touch", {})
        with anyio.fail_after(5):
            await store.both_arms_deleted.wait()
        assert await store.get(key) is None


async def test_a_user_handler_receives_the_notification_the_eviction_consumed() -> None:
    """Eviction is a tee, not a filter: the warm entry is gone by the time the
    user's handler sees the notification, and nothing else is delivered."""
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    client = Client(_list_changed_server(), mode="legacy", message_handler=collect)

    async with client:
        key = await _warm_tools_list_entry(client)
        await client.call_tool("touch", {})
        with anyio.fail_after(5):
            await seen.wait()
        # The wrap awaits the eviction before delegating, so delivery implies the
        # entry is already gone.
        assert await _coordinator(client)._store.get(key) is None

    assert received == snapshot([ToolListChangedNotification()])


async def test_non_notification_items_pass_through_to_the_user_handler_untouched() -> None:
    """The wrap delegates non-notification items verbatim and leaves the cache
    alone. Transport `Exception` items only exist on stream-backed dispatchers,
    which the in-process path cannot produce, so the installed handler is invoked
    directly; `RequestResponder` items take this same non-notification branch."""
    received: list[IncomingMessage] = []

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    client = Client(_list_changed_server(), message_handler=collect)

    async with client:
        installed = client.session._message_handler
        assert installed is not collect  # the wrap, not the bare user handler
        key = await _warm_tools_list_entry(client)
        fault = RuntimeError("stream broke")
        await installed(fault)
        assert received == [fault]
        assert await _coordinator(client)._store.get(key) is not None


async def test_a_raising_eviction_does_not_block_notification_delivery(caplog: pytest.LogCaptureFixture) -> None:
    """The eviction boundary contains cache faults: a coordinator that raises is
    logged and the user's handler still receives the notification."""

    class _ExplodingCache(ClientResponseCache):
        async def evict_for_notification(self, notification: ServerNotification) -> None:
            raise RuntimeError("cache bug")

    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    client = Client(_list_changed_server(), mode="legacy", message_handler=collect)
    # The wrap reads `_response_cache` when the session is built, so swapping the
    # coordinator pre-enter routes eviction through the exploding subclass.
    client._response_cache = _ExplodingCache(
        store=InMemoryResponseCacheStore(),
        partition="",
        arm_id="arm",
        default_ttl_ms=0,
        clock=time.time,
        share_public=False,
        negotiated_version=lambda: None,
    )

    async with client:
        await client.call_tool("touch", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert received == snapshot([ToolListChangedNotification()])
    assert "Response cache eviction failed; the notification is still delivered" in [
        record.message for record in caplog.records
    ]


# --- The cacheable verbs ---


class _ManualClock:
    """Injected wall clock: tests advance `now` instead of sleeping."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _varying_tools_server(
    *, ttl_ms: int = 60_000, scope: Literal["public", "private"] = "private"
) -> tuple[Server[Any], list[str | None]]:
    """In-process server whose every tools/list fetch returns a distinct tool name
    `t<n>`, so a served entry is distinguishable from a refetch by payload, not just
    by handler count. The fetch log records each request's cursor."""
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        return ListToolsResult(tools=[Tool(name=f"t{len(fetches) - 1}", input_schema={"type": "object"})])

    server = Server(
        "varying", on_list_tools=list_tools, cache_hints={"tools/list": CacheHint(ttl_ms=ttl_ms, scope=scope)}
    )
    return server, fetches


def _tool_names(result: ListToolsResult) -> list[str]:
    return [tool.name for tool in result.tools]


async def test_a_second_list_tools_within_the_ttl_is_served_from_the_cache() -> None:
    """SEP-2549: a result carrying a `ttlMs` hint is reusable until it expires — the
    second `list_tools` is served from the cache without reaching the server."""
    server, fetches = _varying_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        first = await client.list_tools()
        second = await client.list_tools()

    assert fetches == [None]
    assert second == first


async def test_an_expired_entry_is_refetched() -> None:
    """An entry is fresh strictly within its `ttlMs`: once the (injected) clock passes
    expiry, the next `list_tools` fetches again and serves the new listing."""
    clock = _ManualClock()
    server, fetches = _varying_tools_server(ttl_ms=60_000)

    async with Client(server, cache=CacheConfig(clock=clock)) as client:
        assert _tool_names(await client.list_tools()) == ["t0"]
        clock.now += 60.0
        assert _tool_names(await client.list_tools()) == ["t1"]

    assert fetches == [None, None]


async def test_each_list_verb_caches_independently_under_its_own_method() -> None:
    """Cache keys discriminate by method (spec MUST): warming one list verb never
    serves another — each of the four fetches once, and each repeat call is served
    from that verb's own entry."""
    fetched: list[str] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetched.append("tools/list")
        return ListToolsResult(tools=[])

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        fetched.append("prompts/list")
        return ListPromptsResult(prompts=[])

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        fetched.append("resources/list")
        return ListResourcesResult(resources=[])

    async def list_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        fetched.append("resources/templates/list")
        return ListResourceTemplatesResult(resource_templates=[])

    hint = CacheHint(ttl_ms=60_000)
    server = Server(
        "all-lists",
        on_list_tools=list_tools,
        on_list_prompts=list_prompts,
        on_list_resources=list_resources,
        on_list_resource_templates=list_templates,
        cache_hints={
            "tools/list": hint,
            "prompts/list": hint,
            "resources/list": hint,
            "resources/templates/list": hint,
        },
    )

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        # First round: every verb fetches, despite the previously warmed entries.
        await client.list_tools()
        await client.list_prompts()
        await client.list_resources()
        await client.list_resource_templates()
        # Second round: every verb is served from its own entry.
        await client.list_tools()
        await client.list_prompts()
        await client.list_resources()
        await client.list_resource_templates()

    assert fetched == ["tools/list", "prompts/list", "resources/list", "resources/templates/list"]


async def test_read_resource_caches_per_uri() -> None:
    """Cache keys discriminate by result-affecting params (spec MUST): two uris cache
    independently, and each repeat read is served from its own entry."""
    reads: list[str] = []

    async def read(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        reads.append(params.uri)
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=params.uri)])

    server = Server("res", on_read_resource=read, cache_hints={"resources/read": CacheHint(ttl_ms=60_000)})

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        first_a = await client.read_resource("memo://a")
        first_b = await client.read_resource("memo://b")
        assert await client.read_resource("memo://a") == first_a
        assert await client.read_resource("memo://b") == first_b

    assert reads == ["memo://a", "memo://b"]


def _paginated_tools_server() -> tuple[Server[Any], list[str | None]]:
    """In-process server with a cacheable first page; the cursor `"expired"` is
    rejected with INVALID_PARAMS (the spec's expired-cursor signal) and `"fail"`
    with INTERNAL_ERROR (any other continuation failure)."""
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        cursor = params.cursor if params is not None else None
        fetches.append(cursor)
        if cursor is None:
            first_page = Tool(name="first-page", input_schema={"type": "object"})
            return ListToolsResult(tools=[first_page], next_cursor="page-2")
        if cursor == "page-2":
            return ListToolsResult(tools=[Tool(name="second-page", input_schema={"type": "object"})])
        if cursor == "fail":
            raise MCPError(code=INTERNAL_ERROR, message="transient failure")
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown cursor: {cursor!r}")

    server = Server("paginated", on_list_tools=list_tools, cache_hints={"tools/list": CacheHint(ttl_ms=60_000)})
    return server, fetches


async def test_cursor_continuations_neither_read_nor_write_the_cache() -> None:
    """Only cursor-less calls participate in caching (SDK-defined single-page entry):
    a continuation fetches despite a warm entry, and its page does not replace it."""
    server, fetches = _paginated_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert _tool_names(await client.list_tools()) == ["first-page"]
        # Not served from the warm entry, despite cache_mode="use".
        assert _tool_names(await client.list_tools(cursor="page-2")) == ["second-page"]
        # The continuation page did not overwrite the cursor-less entry.
        assert _tool_names(await client.list_tools()) == ["first-page"]

    assert fetches == [None, "page-2"]


async def test_an_expired_cursor_rejection_evicts_the_methods_entry() -> None:
    """Spec SHOULD: an INVALID_PARAMS rejection of a continuation cursor means the
    listing changed, so the cached first page is evicted and refetched next time."""
    server, fetches = _paginated_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        await client.list_tools()
        with pytest.raises(MCPError) as exc_info:
            await client.list_tools(cursor="expired")
        assert exc_info.value.code == INVALID_PARAMS
        await client.list_tools()

    assert fetches == [None, "expired", None]


async def test_an_expired_cursor_rejection_under_bypass_does_not_evict() -> None:
    """`cache_mode="bypass"` means no cache side-effects at all: the same
    INVALID_PARAMS rejection leaves the warm entry in place."""
    server, fetches = _paginated_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        await client.list_tools()
        with pytest.raises(MCPError) as exc_info:
            await client.list_tools(cursor="expired", cache_mode="bypass")
        assert exc_info.value.code == INVALID_PARAMS
        await client.list_tools()  # still served from the warm entry

    assert fetches == [None, "expired"]


async def test_a_non_cursor_error_on_a_continuation_does_not_evict() -> None:
    """Only INVALID_PARAMS signals cursor expiry: a continuation failing with any
    other code re-raises without disturbing the warm entry."""
    server, fetches = _paginated_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        await client.list_tools()
        with pytest.raises(MCPError) as exc_info:
            await client.list_tools(cursor="fail")
        assert exc_info.value.code == INTERNAL_ERROR
        await client.list_tools()  # still served from the warm entry

    assert fetches == [None, "fail"]


async def test_bypass_neither_serves_nor_disturbs_a_warm_entry() -> None:
    """`cache_mode="bypass"` fetches fresh without reading the warm entry and without
    storing the fetched result over it."""
    server, fetches = _varying_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert _tool_names(await client.list_tools()) == ["t0"]
        assert _tool_names(await client.list_tools(cache_mode="bypass")) == ["t1"]
        # The bypass fetch neither served nor replaced the entry.
        assert _tool_names(await client.list_tools()) == ["t0"]

    assert fetches == [None, None]


async def test_refresh_skips_the_read_and_stores_the_refetched_result() -> None:
    """`cache_mode="refresh"` ignores the warm entry, fetches, and re-stores: the
    following plain call serves the refreshed listing."""
    server, fetches = _varying_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert _tool_names(await client.list_tools()) == ["t0"]
        assert _tool_names(await client.list_tools(cache_mode="refresh")) == ["t1"]
        assert _tool_names(await client.list_tools()) == ["t1"]

    assert fetches == [None, None]


async def test_refresh_storing_a_ttl_zero_result_purges_the_warm_entry() -> None:
    """A refresh whose refetched result is uncacheable (`ttlMs: 0`) purges the warm
    entry instead of leaving it to be served again — the refetch superseded it."""
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        ttl_ms = 60_000 if len(fetches) == 1 else 0
        tool = Tool(name=f"t{len(fetches) - 1}", input_schema={"type": "object"})
        return ListToolsResult(tools=[tool], ttl_ms=ttl_ms)

    server = Server("flip", on_list_tools=list_tools)

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert _tool_names(await client.list_tools()) == ["t0"]
        assert _tool_names(await client.list_tools(cache_mode="refresh")) == ["t1"]
        # t0 must not resurface: the refresh purged it, and t1 (ttl 0) was never stored.
        assert _tool_names(await client.list_tools()) == ["t2"]

    assert fetches == [None, None, None]


async def test_cache_mode_is_inert_when_caching_is_disabled() -> None:
    """With `cache=False` the verbs accept `cache_mode` but every call goes to the
    server — no reads, no writes, no eviction machinery. SDK-defined off switch."""
    server, fetches = _varying_tools_server()

    async with Client(server, cache=False) as client:
        await client.list_tools()
        await client.list_tools(cache_mode="use")
        await client.list_tools(cache_mode="refresh")

    assert fetches == [None, None, None]


@pytest.mark.parametrize(
    "seed",
    [{"request_state": "round-2"}, {"input_responses": {"ask": ElicitResult(action="decline")}}],
    ids=["request_state", "input_responses"],
)
async def test_a_seeded_read_resource_skips_the_cache_and_ignores_cache_mode(seed: dict[str, Any]) -> None:
    """Spec MUST: results of requests carrying `inputResponses` or `requestState` are
    never cached. A seeded read is a resumption: it is not served from the warm entry
    under "use", does not purge it under "refresh", and stores nothing — the final
    plain read still serves the original entry."""
    reads = 0

    async def read(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        nonlocal reads
        reads += 1
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=f"v{reads}")], ttl_ms=60_000)

    server = Server("res", on_read_resource=read)

    def text(result: ReadResourceResult) -> str:
        content = result.contents[0]
        assert isinstance(content, TextResourceContents)
        return content.text

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert text(await client.read_resource("memo://a")) == "v1"
        assert text(await client.read_resource("memo://a", **seed)) == "v2"
        assert text(await client.read_resource("memo://a", **seed, cache_mode="refresh")) == "v3"
        # The warm v1 entry survived both seeded calls: nothing read, written, or purged.
        assert text(await client.read_resource("memo://a")) == "v1"

    assert reads == 3


async def test_a_terminal_read_reached_through_driver_rounds_is_never_cached() -> None:
    """Spec MUST: the driver's retry rounds carry `inputResponses`, so a terminal
    result reached through them is not cached — a repeat read goes back to the wire
    (and drives the rounds again)."""
    seeded_rounds: list[bool] = []
    ask = ElicitRequest(
        params=ElicitRequestFormParams(
            message="What is your name?",
            requested_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
    )

    async def read(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> ReadResourceResult | InputRequiredResult:
        seeded_rounds.append(params.input_responses is not None)
        if params.input_responses is not None:
            return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text="terminal")], ttl_ms=60_000)
        return InputRequiredResult(input_requests={"ask": ask})

    async def elicitation_callback(
        context: Any, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        return ElicitResult(action="accept", content={"name": "Ada"})

    server = Server("gated", on_read_resource=read)

    with anyio.fail_after(5):
        async with Client(
            server, elicitation_callback=elicitation_callback, cache=CacheConfig(clock=_ManualClock())
        ) as client:
            first = await client.read_resource("memo://gated")
            second = await client.read_resource("memo://gated")

    assert isinstance(first.contents[0], TextResourceContents) and first.contents[0].text == "terminal"
    assert second == first
    # Two wire rounds per call: the second call was not served from the cache.
    assert seeded_rounds == [False, True, False, True]


async def test_a_refresh_that_resolves_to_input_required_purges_the_warm_entry() -> None:
    """SDK-defined supersession rule: a refresh whose unseeded first round comes back
    input_required cannot store its driven terminal result (the rounds carry
    `inputResponses` — spec MUST), but it still purges the warm entry — the pre-flip
    value must not resurface on the next plain read."""
    reads = 0
    ask = ElicitRequest(
        params=ElicitRequestFormParams(
            message="What is your name?",
            requested_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
    )

    async def read(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> ReadResourceResult | InputRequiredResult:
        nonlocal reads
        reads += 1
        # The resource starts plain and then flips to requiring input.
        if reads > 1 and params.input_responses is None:
            return InputRequiredResult(input_requests={"ask": ask})
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=f"v{reads}")], ttl_ms=60_000)

    async def elicitation_callback(
        context: Any, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        return ElicitResult(action="accept", content={"name": "Ada"})

    server = Server("flipping", on_read_resource=read)

    def text(result: ReadResourceResult) -> str:
        content = result.contents[0]
        assert isinstance(content, TextResourceContents)
        return content.text

    with anyio.fail_after(5):
        async with Client(
            server, elicitation_callback=elicitation_callback, cache=CacheConfig(clock=_ManualClock())
        ) as client:
            assert text(await client.read_resource("memo://a")) == "v1"  # cached for 60s
            assert text(await client.read_resource("memo://a", cache_mode="refresh")) == "v3"
            # v1 must not resurface: the refresh purged it, and the driven terminal
            # result (v3) was never stored — the plain read drives fresh rounds.
            assert text(await client.read_resource("memo://a")) == "v5"

    assert reads == 5


def _output_schema_server(call_result: CallToolResult) -> tuple[Server[Any], list[str | None]]:
    """In-process server whose one tool declares an output schema; `call_tool` returns
    the canned `call_result` so tests choose whether it satisfies that schema."""
    fetches: list[str | None] = []
    tool = Tool(
        name="run",
        input_schema={"type": "object"},
        output_schema={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
    )

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        return ListToolsResult(tools=[tool])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "run"
        return call_result

    server = Server(
        "schemas",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        cache_hints={"tools/list": CacheHint(ttl_ms=60_000)},
    )
    return server, fetches


async def test_a_listing_served_from_a_shared_store_rebuilds_output_schemas() -> None:
    """A fresh client whose first `list_tools` is served from a pre-warmed shared
    store absorbs the served listing into the session: `call_tool` validates its
    structured output against the absorbed schema without ever fetching the listing
    from the server (the fetch log stays at the warming client's one entry)."""
    call_result = CallToolResult(content=[TextContent(text="ok")], structured_content={"n": 1})
    server, fetches = _output_schema_server(call_result)
    config = CacheConfig(store=InMemoryResponseCacheStore(), partition="p", target_id="svc", clock=_ManualClock())

    async with Client(server, cache=config) as warming:
        listing = await warming.list_tools()

    async with Client(server, cache=config) as fresh:
        assert await fresh.list_tools() == listing  # served from the shared store
        result = await fresh.call_tool("run", {})

    assert result.structured_content == {"n": 1}
    # One wire fetch total: the fresh client's listing AND the validation schema both
    # came from the served entry (a starved schema cache would have re-listed here).
    assert fetches == [None]


async def test_validation_from_a_served_listing_rejects_missing_structured_content() -> None:
    """The schema absorbed from a served listing is enforced, not just present: a tool
    result without structured content fails validation in the fresh client, again
    without any wire refetch of the listing."""
    server, fetches = _output_schema_server(CallToolResult(content=[TextContent(text="ok")]))
    config = CacheConfig(store=InMemoryResponseCacheStore(), partition="p", target_id="svc", clock=_ManualClock())

    async with Client(server, cache=config) as warming:
        await warming.list_tools()

    async with Client(server, cache=config) as fresh:
        await fresh.list_tools()
        with pytest.raises(RuntimeError) as exc_info:
            await fresh.call_tool("run", {})

    assert str(exc_info.value) == snapshot("Tool run has an output schema but did not return structured content")
    assert fetches == [None]


async def test_a_cache_hit_listing_still_mirrors_x_mcp_headers_on_tools_call() -> None:
    """A fresh client serving tools/list from a pre-warmed shared store still mirrors
    `x-mcp-header` arguments into `Mcp-Param-*` headers on a later `tools/call`: the
    arg→header maps are rebuilt from the served listing. Asserted at the wire (over
    the in-process HTTP bridge) because the client never surfaces outgoing headers."""
    tool = Tool(
        name="run",
        input_schema={"type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "Region"}}},
    )

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[tool], ttl_ms=60_000)

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "run"
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("headers", on_list_tools=list_tools, on_call_tool=call_tool)

    posts: list[httpx.Request] = []

    async def on_request(request: httpx.Request) -> None:
        posts.append(request)

    config = CacheConfig(store=InMemoryResponseCacheStore(), partition="p", target_id="svc")
    discover = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="srv", version="0"),
    )

    with anyio.fail_after(5):
        async with mounted_app(server, on_request=on_request) as (http, _):
            warming = Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
                cache=config,
            )
            async with warming:
                await warming.list_tools()
            fresh = Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
                cache=config,
            )
            async with fresh:
                await fresh.list_tools()
                await fresh.call_tool("run", {"region": "us-west1"})

            # Exactly one tools/list reached the wire: the fresh client served from the store.
            assert [json.loads(request.content)["method"] for request in posts] == ["tools/list", "tools/call"]
            assert posts[-1].headers["mcp-param-region"] == "us-west1"


async def test_a_tools_list_changed_notification_makes_the_next_list_refetch() -> None:
    """Spec SHOULD: a list_changed notification invalidates the cached listing — the
    next `list_tools` goes back to the server. Runs on a legacy session (the only
    in-process transport that delivers standalone notifications) with `default_ttl_ms`
    providing the cached entry, proving eviction is era-independent."""
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        return ListToolsResult(tools=[Tool(name="touch", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "touch"
        await ctx.session.send_tool_list_changed()
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("notify", on_list_tools=list_tools, on_call_tool=call_tool)

    # The wrap evicts before delegating, so delivery here implies eviction completed.
    delivered = anyio.Event()

    async def on_message(message: IncomingMessage) -> None:
        assert isinstance(message, ToolListChangedNotification)  # the only message this server emits
        delivered.set()

    client = Client(server, mode="legacy", cache=CacheConfig(default_ttl_ms=60_000), message_handler=on_message)
    async with client:
        await client.list_tools()
        await client.list_tools()
        assert fetches == [None]  # cached via default_ttl_ms on the legacy session
        await client.call_tool("touch", {})
        with anyio.fail_after(5):
            await delivered.wait()
        await client.list_tools()

    assert fetches == [None, None]


async def test_a_resource_updated_notification_evicts_that_uris_read_entry() -> None:
    """Spec SHOULD: `notifications/resources/updated` invalidates the cached read for
    its uri. This is also the uri-form agreement proof: the entry stored under the
    string passed to `read_resource` is the one the notification's `params.uri`
    evicts — the next read of that uri refetches."""
    uri = "memo://cached"
    reads: list[str] = []

    async def read(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        reads.append(params.uri)
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=f"v{len(reads)}")])

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="poke", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "poke"
        await ctx.session.send_resource_updated(uri)
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("updates", on_read_resource=read, on_list_tools=list_tools, on_call_tool=call_tool)

    delivered: list[str] = []
    seen = anyio.Event()

    async def on_message(message: IncomingMessage) -> None:
        assert isinstance(message, ResourceUpdatedNotification)  # the only message this server emits
        delivered.append(message.params.uri)
        seen.set()

    client = Client(server, mode="legacy", cache=CacheConfig(default_ttl_ms=60_000), message_handler=on_message)
    async with client:
        await client.read_resource(uri)
        await client.read_resource(uri)
        assert reads == [uri]  # cached via default_ttl_ms on the legacy session
        await client.call_tool("poke", {})
        with anyio.fail_after(5):
            await seen.wait()
        await client.read_resource(uri)

    # The notification carried the exact string the entry was stored under.
    assert delivered == [uri]
    assert reads == [uri, uri]


async def test_the_modern_in_process_path_drops_the_eviction_notification() -> None:
    """Pins the documented transport gap: the default in-process connection
    (mode="auto", DirectDispatcher) does not deliver standalone server notifications,
    so a tools/list_changed emitted mid-call never reaches the cache - the warm entry
    survives and the next `list_tools` is still served from it. Delivery on this path
    would happen inline within the awaited `call_tool`, so asserting after it returns
    is race-free. If this test starts failing, the path gained delivery: flip the
    `docs/advanced/caching.md` eviction caveat and the legacy-mode notification tests."""
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        return ListToolsResult(tools=[Tool(name="touch", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "touch"
        await ctx.session.send_tool_list_changed()
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server(
        "notify",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        cache_hints={"tools/list": CacheHint(ttl_ms=60_000)},
    )

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        await client.list_tools()
        await client.call_tool("touch", {})
        await client.list_tools()  # still served from the warm entry: no eviction arrived

    assert fetches == [None]


async def test_a_discover_result_never_enters_the_response_cache() -> None:
    """SDK ruling (documented): the response cache covers the five `Client` verbs
    only. The connect-time server/discover result is never stored, even when it
    carries a `ttlMs` hint - a persisted `prior_discover`'s freshness is the user's
    bookkeeping (`DiscoverResult` carries the parsed hints for it)."""
    server = Server("hinted", cache_hints={"server/discover": CacheHint(ttl_ms=60_000)})

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        discover = client.session.discover_result
        assert discover is not None
        assert discover.ttl_ms == 60_000  # the hint arrived with the probe result...
        store = _coordinator(client)._store
        assert isinstance(store, InMemoryResponseCacheStore)
        assert store._entries == {}  # ...and nothing entered the cache


# --- The inbound ttlMs clamp (parse seam) ---


@pytest.mark.parametrize("wire_ttl", [-5, -5.0])
async def test_a_negative_inbound_ttl_is_served_as_zero_and_never_cached(wire_ttl: int | float) -> None:
    """Spec SHOULD (2026-07-28 caching): a negative `ttlMs` is treated as 0 — the
    call succeeds instead of failing the `ge=0` wire validation, and a zero ttl is
    never stored, so the next call goes back to the server. The peer is scripted
    over raw streams because an SDK server cannot emit a negative ttl (server-side
    `ge=0` enforcement)."""
    listings_served = 0

    async def scripted_server(streams: MessageStream) -> None:
        nonlocal listings_served
        server_read, server_write = streams
        async for message in server_read:
            assert isinstance(message, SessionMessage)
            frame = message.message
            assert isinstance(frame, types.JSONRPCRequest)
            if frame.method == "server/discover":
                result: dict[str, Any] = {
                    "supportedVersions": [LATEST_MODERN_VERSION],
                    "capabilities": {},
                    "serverInfo": {"name": "negative-ttl", "version": "0.0.1"},
                    "resultType": "complete",
                    "ttlMs": 0,
                }
            else:
                assert frame.method == "tools/list"
                listings_served += 1
                result = {"resultType": "complete", "tools": [], "ttlMs": wire_ttl, "cacheScope": "private"}
            await server_write.send(SessionMessage(types.JSONRPCResponse(jsonrpc="2.0", id=frame.id, result=result)))

    @asynccontextmanager
    async def scripted_transport() -> AsyncIterator[TransportStreams]:
        async with (
            create_client_server_memory_streams() as ((client_read, client_write), server_streams),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(scripted_server, server_streams)
            yield client_read, client_write
            tg.cancel_scope.cancel()

    with anyio.fail_after(5):
        async with Client(scripted_transport(), mode="auto") as client:
            first = await client.list_tools()
            second = await client.list_tools()

    assert first.ttl_ms == 0
    assert second.ttl_ms == 0
    assert listings_served == 2  # the clamped-to-zero ttl was never stored: the second call re-fetched


@pytest.mark.parametrize("wire_ttl", [-5, -5.0])
async def test_a_negative_discover_ttl_still_connects_modern_in_auto_mode(wire_ttl: int | float) -> None:
    """Spec SHOULD (2026-07-28 caching) — silent-downgrade regression: before the
    parse-seam clamp, a negative `ttlMs` on `server/discover` failed `DiscoverResult`
    validation inside the mode='auto' probe, which reads as "not modern evidence" and
    silently fell back to the legacy initialize handshake. Clamped, the probe adopts
    the modern era and the result carries `ttl_ms == 0` — for float negatives too,
    the same as the tools/list seam (both call the shared clamp)."""
    methods_seen: list[str] = []

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        async for message in server_read:
            assert isinstance(message, SessionMessage)
            frame = message.message
            assert isinstance(frame, types.JSONRPCRequest)
            methods_seen.append(frame.method)
            # A legacy downgrade would send `initialize` next; fail loudly instead.
            assert frame.method == "server/discover"
            result: dict[str, Any] = {
                "supportedVersions": [LATEST_MODERN_VERSION],
                "capabilities": {},
                "serverInfo": {"name": "negative-ttl", "version": "0.0.1"},
                "resultType": "complete",
                "ttlMs": wire_ttl,
            }
            await server_write.send(SessionMessage(types.JSONRPCResponse(jsonrpc="2.0", id=frame.id, result=result)))

    @asynccontextmanager
    async def scripted_transport() -> AsyncIterator[TransportStreams]:
        async with (
            create_client_server_memory_streams() as ((client_read, client_write), server_streams),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(scripted_server, server_streams)
            yield client_read, client_write
            tg.cancel_scope.cancel()

    with anyio.fail_after(5):
        async with Client(scripted_transport(), mode="auto") as client:
            assert client.protocol_version == LATEST_MODERN_VERSION
            discover = client.session.discover_result
            assert discover is not None
            assert discover.ttl_ms == 0

    assert methods_seen == ["server/discover"]


# --- Hardening e2e ---


def _versioned_read_server(*, ttl_ms: int = 60_000) -> tuple[Server[Any], list[str]]:
    """In-process server whose every resources/read fetch returns a distinct payload
    `v<n>`, so a served entry is distinguishable from a refetch. The read log records
    each request's uri."""
    reads: list[str] = []

    async def read(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        reads.append(params.uri)
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=f"v{len(reads)}")], ttl_ms=ttl_ms)

    return Server("versioned-reads", on_read_resource=read), reads


def _resource_text(result: ReadResourceResult) -> str:
    content = result.contents[0]
    assert isinstance(content, TextResourceContents)
    return content.text


async def test_each_notification_evicts_exactly_its_entries_end_to_end() -> None:
    """Spec SHOULD (notifications invalidate) plus its negative space, end to end.

    Steps:
      1. Prime all four list verbs and two resource reads; a second round of calls
         is served entirely from the cache.
      2. tools/list_changed -> only tools/list refetches.
      3. resources/list_changed -> resources/list AND resources/templates/list
         refetch; tools, prompts, and both reads stay served.
      4. resources/updated(X) -> only the X read refetches; Y and every list stay
         served.

    Runs on a legacy session (the in-process transport that delivers standalone
    notifications) with `default_ttl_ms` providing the cached entries.
    """
    uri_x, uri_y = "memo://x", "memo://y"
    fetched: list[str] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetched.append("tools/list")
        return ListToolsResult(tools=[Tool(name="notify", input_schema={"type": "object"})])

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        fetched.append("prompts/list")
        return ListPromptsResult(prompts=[])

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        fetched.append("resources/list")
        return ListResourcesResult(resources=[])

    async def list_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        fetched.append("resources/templates/list")
        return ListResourceTemplatesResult(resource_templates=[])

    async def read(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        fetched.append(f"resources/read {params.uri}")
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text="body")])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "notify"
        kind = (params.arguments or {})["kind"]
        if kind == "tools":
            await ctx.session.send_tool_list_changed()
        elif kind == "resources":
            await ctx.session.send_resource_list_changed()
        else:
            assert kind == "updated-x"
            await ctx.session.send_resource_updated(uri_x)
        return CallToolResult(content=[TextContent(text="sent")])

    server = Server(
        "notifier",
        on_list_tools=list_tools,
        on_list_prompts=list_prompts,
        on_list_resources=list_resources,
        on_list_resource_templates=list_templates,
        on_read_resource=read,
        on_call_tool=call_tool,
    )

    delivered: list[IncomingMessage] = []
    eviction_done = [anyio.Event() for _ in range(3)]

    async def on_message(message: IncomingMessage) -> None:
        # The wrap evicts before delegating, so each event implies its eviction completed.
        delivered.append(message)
        eviction_done[len(delivered) - 1].set()

    client = Client(
        server,
        mode="legacy",
        cache=CacheConfig(default_ttl_ms=60_000, clock=_ManualClock()),
        message_handler=on_message,
    )

    async with client:

        async def served_round() -> list[str]:
            """Call every cacheable verb once; return the calls that reached the server."""
            before = len(fetched)
            await client.list_tools()
            await client.list_prompts()
            await client.list_resources()
            await client.list_resource_templates()
            await client.read_resource(uri_x)
            await client.read_resource(uri_y)
            return fetched[before:]

        assert await served_round() == [
            "tools/list",
            "prompts/list",
            "resources/list",
            "resources/templates/list",
            f"resources/read {uri_x}",
            f"resources/read {uri_y}",
        ]
        assert await served_round() == []  # everything primed and served

        await client.call_tool("notify", {"kind": "tools"})
        with anyio.fail_after(5):
            await eviction_done[0].wait()
        assert await served_round() == ["tools/list"]

        await client.call_tool("notify", {"kind": "resources"})
        with anyio.fail_after(5):
            await eviction_done[1].wait()
        assert await served_round() == ["resources/list", "resources/templates/list"]

        await client.call_tool("notify", {"kind": "updated-x"})
        with anyio.fail_after(5):
            await eviction_done[2].wait()
        assert await served_round() == [f"resources/read {uri_x}"]

    assert delivered == [
        ToolListChangedNotification(),
        ResourceListChangedNotification(),
        ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri=uri_x)),
    ]


async def test_private_entries_never_cross_partitions_between_clients_sharing_a_store() -> None:
    """Spec MUST (`"private"` never crosses authorization contexts), end to end: two
    clients sharing one store and server identity but holding different partitions
    each fetch their own listing - the second client is never served the first's
    private-scoped entry."""
    server, fetches = _varying_tools_server()
    store = InMemoryResponseCacheStore()

    def config(partition: str) -> CacheConfig:
        return CacheConfig(store=store, partition=partition, target_id="svc", clock=_ManualClock())

    async with Client(server, cache=config("tenant-a")) as tenant_a:
        assert _tool_names(await tenant_a.list_tools()) == ["t0"]
    async with Client(server, cache=config("tenant-b")) as tenant_b:
        assert _tool_names(await tenant_b.list_tools()) == ["t1"]  # fetched, not tenant-a's entry

    assert fetches == [None, None]


async def test_a_server_stamped_public_entry_does_not_cross_partitions_by_default() -> None:
    """SDK security default (deviates from the ts SDK), end to end: even when the
    server stamps `cacheScope: "public"`, the default config keys the public arm by
    partition - a same-partition client is served from the store, a different-
    partition client fetches its own listing."""
    server, fetches = _varying_tools_server(scope="public")
    store = InMemoryResponseCacheStore()

    def config(partition: str) -> CacheConfig:
        return CacheConfig(store=store, partition=partition, target_id="svc", clock=_ManualClock())

    async with Client(server, cache=config("tenant-a")) as tenant_a:
        assert _tool_names(await tenant_a.list_tools()) == ["t0"]
    async with Client(server, cache=config("tenant-a")) as same_partition:
        assert _tool_names(await same_partition.list_tools()) == ["t0"]  # served from the store
    async with Client(server, cache=config("tenant-b")) as tenant_b:
        assert _tool_names(await tenant_b.list_tools()) == ["t1"]  # fetched

    assert fetches == [None, None]


async def test_share_public_serves_a_server_stamped_public_entry_across_partitions() -> None:
    """SDK-defined opt-in, end to end: with `share_public=True` the public arm drops
    the partition, so the second tenant's first list_tools is served from the first
    tenant's server-asserted-public entry without a fetch."""
    server, fetches = _varying_tools_server(scope="public")
    store = InMemoryResponseCacheStore()

    def config(partition: str) -> CacheConfig:
        return CacheConfig(store=store, partition=partition, target_id="svc", share_public=True, clock=_ManualClock())

    async with Client(server, cache=config("tenant-a")) as tenant_a:
        assert _tool_names(await tenant_a.list_tools()) == ["t0"]
    async with Client(server, cache=config("tenant-b")) as tenant_b:
        assert _tool_names(await tenant_b.list_tools()) == ["t0"]  # served across partitions

    assert fetches == [None]


async def test_same_partition_clients_share_read_entries_through_the_store() -> None:
    """SDK-defined sharing, end to end: two clients with the same store, server
    identity, and partition share `resources/read` entries - the second client's
    first read is served from the store without invoking the handler. (The
    tools/list case, including its absorbed derived state, is pinned by the
    shared-store absorption tests above.)"""
    server, reads = _versioned_read_server()
    store = InMemoryResponseCacheStore()

    def config() -> CacheConfig:
        return CacheConfig(store=store, partition="p", target_id="svc", clock=_ManualClock())

    async with Client(server, cache=config()) as first:
        first_result = await first.read_resource("memo://a")
    async with Client(server, cache=config()) as second:
        assert await second.read_resource("memo://a") == first_result

    assert reads == ["memo://a"]


async def test_mutating_returned_results_never_corrupts_the_cached_entry() -> None:
    """SDK-defined deep-copy isolation, both directions, end to end: mutating the
    result a verb returned (the very object the write deep-copied from) and mutating
    a served hit (the object the read deep-copied out) both leave the stored entry
    untouched - every later call serves the pristine listing from the single fetch."""
    server, fetches = _varying_tools_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        first = await client.list_tools()
        first.tools[0].name = "tampered-after-fetch"
        second = await client.list_tools()  # cache hit, unaffected by the mutation
        assert _tool_names(second) == ["t0"]
        second.tools[0].name = "tampered-after-serve"
        assert _tool_names(await client.list_tools()) == ["t0"]  # still pristine

    assert fetches == [None]


async def test_a_legacy_peer_injecting_cache_hints_caches_nothing() -> None:
    """SDK-defined era gate, end to end: `ttlMs`/`cacheScope` are 2026-07-28
    assertions, but a 2025 peer can still put the keys on the wire. On a legacy
    session with the default config nothing is cached - the second list_tools
    reaches the peer and the store stays empty on both arms. The peer is scripted
    over raw streams because an SDK server strips the hint fields when serializing
    for a 2025 session, so the injection is not expressible through the server API."""
    listings_served = 0

    async def scripted_server(streams: MessageStream) -> None:
        nonlocal listings_served
        server_read, server_write = streams
        async for message in server_read:
            assert isinstance(message, SessionMessage)
            frame = message.message
            if isinstance(frame, types.JSONRPCNotification):
                assert frame.method == "notifications/initialized"
                continue
            assert isinstance(frame, types.JSONRPCRequest)
            if frame.method == "initialize":
                result: dict[str, Any] = {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "serverInfo": {"name": "legacy-injector", "version": "0.0.1"},
                }
            else:
                assert frame.method == "tools/list"
                listings_served += 1
                result = {"tools": [], "ttlMs": 60_000, "cacheScope": "public"}
            await server_write.send(SessionMessage(types.JSONRPCResponse(jsonrpc="2.0", id=frame.id, result=result)))

    @asynccontextmanager
    async def scripted_transport() -> AsyncIterator[TransportStreams]:
        async with (
            create_client_server_memory_streams() as ((client_read, client_write), server_streams),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(scripted_server, server_streams)
            yield client_read, client_write
            tg.cancel_scope.cancel()

    with anyio.fail_after(5):
        async with Client(scripted_transport(), mode="legacy", cache=CacheConfig(clock=_ManualClock())) as client:
            await client.list_tools()
            await client.list_tools()
            store = _coordinator(client)._store
            assert isinstance(store, InMemoryResponseCacheStore)
            assert store._entries == {}  # neither arm holds an entry

    assert listings_served == 2


class _CancelOnSetStore(InMemoryResponseCacheStore):
    """Store whose next `set` awaits a one-shot hook before committing, modelling an
    async store whose commit a cancellation interrupts."""

    def __init__(self) -> None:
        super().__init__()
        self.before_set: Callable[[], Awaitable[None]] | None = None

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        if self.before_set is not None:
            hook, self.before_set = self.before_set, None
            await hook()
        await super().set(key, entry)


async def test_a_verb_cancelled_mid_write_leaves_no_stale_arm_pair() -> None:
    """SDK-defined no-stale-pair invariant, end to end: a verb call cancelled while
    its cache write is mid-set (after the opposite-arm delete) leaves at most one
    entry for the key - here zero - so the superseded entry cannot be served.

    Steps:
      1. The first list_tools stores a public-scoped entry.
      2. A refresh call fetches a private-scoped result; its write deletes the
         public arm first, then the store's `set` is cancelled before committing.
      3. Both arms are empty - never two entries answering for one key - and the
         next call refetches.
    """
    fetches: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        scope: Literal["public", "private"] = "public" if len(fetches) == 1 else "private"
        tool = Tool(name=f"t{len(fetches) - 1}", input_schema={"type": "object"})
        return ListToolsResult(tools=[tool], ttl_ms=60_000, cache_scope=scope)

    server = Server("scope-flip", on_list_tools=list_tools)
    store = _CancelOnSetStore()
    client = Client(server, cache=CacheConfig(store=store, partition="p", target_id="svc", clock=_ManualClock()))

    async with client:
        assert _tool_names(await client.list_tools()) == ["t0"]
        assert len(store._entries) == 1  # the public-arm entry

        with anyio.CancelScope() as scope:

            async def cancel_mid_commit() -> None:
                scope.cancel()
                await anyio.lowlevel.checkpoint()  # the cancellation is delivered here, inside `set`

            store.before_set = cancel_mid_commit
            await client.list_tools(cache_mode="refresh")
        assert scope.cancelled_caught

        # The write deleted the opposite (public) arm before the cancelled set could
        # commit: zero entries, and in particular not the stale pre-refresh one.
        assert store._entries == {}
        assert _tool_names(await client.list_tools()) == ["t2"]  # nothing cached: refetched

    assert fetches == [None, None, None]


async def test_an_eviction_landing_mid_fetch_discards_that_fetchs_write() -> None:
    """Spec-aligned race rule, end to end: a tools/list_changed notification that
    arrives while the tools/list fetch it concerns is still in flight discards that
    fetch's cache write - the store is empty after the call returns and the next
    list_tools refetches (and then caches normally). The server emits the
    notification mid-fetch and waits for the client-side eviction before responding
    (the handler wrap delegates only after evicting), so the interleaving is
    deterministic, not scheduler-dependent."""
    fetches: list[str | None] = []
    evicted = anyio.Event()

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        fetches.append(params.cursor if params is not None else None)
        if len(fetches) == 1:
            await ctx.session.send_tool_list_changed()
            with anyio.fail_after(5):
                await evicted.wait()
        return ListToolsResult(tools=[Tool(name=f"t{len(fetches) - 1}", input_schema={"type": "object"})])

    async def on_message(message: IncomingMessage) -> None:
        assert isinstance(message, ToolListChangedNotification)  # the only message this server emits
        evicted.set()

    server = Server("racer", on_list_tools=list_tools)
    client = Client(
        server,
        mode="legacy",
        cache=CacheConfig(default_ttl_ms=60_000, clock=_ManualClock()),
        message_handler=on_message,
    )

    async with client:
        assert _tool_names(await client.list_tools()) == ["t0"]
        # Empty proves the write was SKIPPED, not stored-then-evicted: the eviction
        # completed strictly before the response (the handler waited for it) and the
        # write runs strictly after - had it landed, the entry would still be here.
        store = _coordinator(client)._store
        assert isinstance(store, InMemoryResponseCacheStore)
        assert store._entries == {}
        assert _tool_names(await client.list_tools()) == ["t1"]  # refetched...
        assert _tool_names(await client.list_tools()) == ["t1"]  # ...and that fetch cached normally

    assert fetches == [None, None]


async def test_read_resource_bypass_neither_serves_nor_disturbs_a_warm_entry() -> None:
    """`cache_mode="bypass"` on `read_resource` fetches fresh without reading the
    warm entry and without storing over it - the following plain read still serves
    the original value. SDK-defined mode semantics (the list-verb counterpart is
    pinned above)."""
    server, reads = _versioned_read_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert _resource_text(await client.read_resource("memo://a")) == "v1"
        assert _resource_text(await client.read_resource("memo://a", cache_mode="bypass")) == "v2"
        assert _resource_text(await client.read_resource("memo://a")) == "v1"  # warm entry intact

    assert reads == ["memo://a", "memo://a"]


async def test_read_resource_refresh_refetches_and_restores() -> None:
    """`cache_mode="refresh"` on `read_resource` skips the warm entry, fetches, and
    re-stores: the following plain read serves the refreshed value."""
    server, reads = _versioned_read_server()

    async with Client(server, cache=CacheConfig(clock=_ManualClock())) as client:
        assert _resource_text(await client.read_resource("memo://a")) == "v1"
        assert _resource_text(await client.read_resource("memo://a", cache_mode="refresh")) == "v2"
        assert _resource_text(await client.read_resource("memo://a")) == "v2"  # the refreshed value re-stored

    assert reads == ["memo://a", "memo://a"]
