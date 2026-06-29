"""`Client` wiring for the response cache: the `cache=` constructor kwarg, server
identity resolution (explicit `target_id`, URL, per-client random), the custom-store
identity guard, the notification-eviction message-handler wrap, and the lazy
negotiated-version supplier. The coordinator's own behavior is covered in
`test_caching.py`; the cached verbs land separately.
"""

import time
from types import TracebackType
from typing import Any

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolResult,
    ListToolsResult,
    ServerNotification,
    TextContent,
    ToolListChangedNotification,
)

from mcp.client import Client
from mcp.client._transport import TransportStreams
from mcp.client.caching import (
    CacheConfig,
    CacheEntry,
    CacheKey,
    ClientResponseCache,
    InMemoryResponseCacheStore,
)
from mcp.server import Server, ServerRequestContext
from mcp.shared.session import RequestResponder

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
