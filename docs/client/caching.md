# Caching hints

Every result a server returns for `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` and `server/discover` carries two fields on the 2026-07-28 protocol: `ttlMs`, how many milliseconds a client may treat the result as fresh, and `cacheScope`, whether a cached result may be shared across users (`"public"`) or belongs to one authorization context (`"private"`).

The server doesn't cache anything. The fields are a *declaration*: "this tool list is the same for everyone and won't change for a minute." A client (or a gateway in front of you) may then skip the round trip. Honoring the hints is the client's choice; emitting them is the server's job, and the SDK does it for you.

Out of the box every result says `ttlMs: 0, cacheScope: "private"`: immediately stale, never shared. That is always safe and always conformant. If your lists really are stable and identical for all callers, say so at construction:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* The map is keyed by **method name**, and the six cacheable methods are the only legal keys. The parameter is typed `Mapping[CacheableMethod, CacheHint]`, so your editor autocompletes the keys and flags a typo before you run; anything that slips past the type checker raises at construction.
* A method you don't mention keeps the defaults. The map is a set of overrides, not a manifest.
* `CacheHint(ttl_ms=5_000)` left `scope` unset, so it stays `"private"`: five seconds of freshness, per caller. Scope and TTL are independent decisions.
* `"server/discover"` is a legal key too, since the discovery result is cacheable like any list.

!!! warning
    `cacheScope: "public"` means *anyone* may be served your cached response. A shared
    gateway will happily hand one user's result to another, even when the request was
    authenticated. Mark a result `"public"` only when it is identical for every caller, and
    never use `cacheScope` as access control: it is a label, not a lock.

## Per-handler override

On the low-level `Server`, handlers build their results by hand, and `ttl_ms` / `cache_scope` are just fields on the result models. A handler that sets them explicitly always wins over the constructor map, field by field:

```python title="server.py" hl_lines="11 17"
--8<-- "docs_src/caching/tutorial002.py"
```

The handler said `ttl_ms=1_000` and nothing about scope. On the wire: `ttlMs: 1000` (the handler's, not the map's `60_000`) and `cacheScope: "public"` (the map's, because the handler left it unset). Explicit beats configured, and configured beats default. This holds per field, so a handler can pin one field and leave the other to the server-wide policy.

This is also the escape hatch for dynamics the constructor can't know: a handler that filters `resources/read` per user can return `cache_scope="private"` for one URI from an otherwise-public server.

One caveat on paginated lists: the protocol requires the **same `cacheScope` on every page** of one list. The constructor map satisfies that by construction, since it's keyed by method, not by page. But a handler that overrides the scope itself owns that consistency: override it on *every* page, never only when a cursor is present, or page one and page two will disagree.

## What the client sees

On a 2026-07-28 session, `Client` honors the hints for you: it has a built-in response cache, on by default. A result that arrives carrying a `ttlMs` is stored, and an identical call within that TTL is served from the cache with no round trip. A result that carries *no* hint is not cached: hint-less results get `CacheConfig.default_ttl_ms`, which defaults to `0` (immediately stale), so a server that declares nothing sees exactly the call-for-call traffic it always did.

```python title="client.py" hl_lines="34 36 39"
--8<-- "docs_src/caching/tutorial003.py"
```

Four calls, three fetches. The second call found a fresh entry and never reached the server; advancing the (injected) clock past the TTL made the third fetch again; the fourth said `cache_mode="refresh"`. That kwarg exists on the five caching verbs (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`):

* `"use"` (the default) serves a fresh entry if there is one, and stores the fetch if not.
* `"refresh"` never serves: it fetches and stores the result, replacing whatever was cached.
* `"bypass"` makes the round trip without touching the cache at all: no read, no write.

One rule sits above `"use"`: **calls carrying `meta` always reach the server.** A request with `meta` set (a progress token, tracing fields) expects a wire request, so under `cache_mode="use"` it is treated as `"refresh"`: the cache read is skipped, and the fetched result still replaces the cached entry. `"bypass"` and an explicit `"refresh"` behave as they always do.

To turn caching off entirely, construct with `Client(server, cache=False)`: every call is a round trip again, and `cache_mode`, while still accepted, does nothing.

Scope is honored automatically too: `"private"` entries are keyed to the cache's *partition* (below), while `"public"` ones may opt into wider sharing. And **notifications beat TTL** for the exact entries they name: a `list_changed` notification evicts the matching cached listing, and `resources/updated` evicts the cached read stored under exactly its URI, however fresh they were. On a 2026-07-28 connection those notifications arrive on a `subscriptions/listen` stream you open with `client.listen(...)`, and eviction completes before your watcher sees the event; **[Subscriptions](subscriptions.md)** is that page.

One caveat on `resources/updated`: eviction is exact-URI only. The store contract has no enumerate or scan operation (same as the reference TypeScript implementation), so a notification carrying a *sub*-resource URI does not evict a cached read of its parent. If your server signals sub-resources this way, refetch the parent with `cache_mode="refresh"`.

### Configuring it: `CacheConfig`

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`: where entries live. The default is a fresh in-memory store per client; pass your own `ResponseCacheStore` implementation (Redis-backed, say) to share a cache across clients or processes. The contract types (`ResponseCacheStore`, `CacheKey`, `CacheEntry`, and the default `InMemoryResponseCacheStore`) are importable from `mcp.client`. A lookup may issue up to two sequential store `get`s (the private arm, then the public one), so size a remote store's latency expectations accordingly. A custom store **requires** an explicit `partition`.
* `partition`: the authorization-context label that keeps one principal's `"private"` entries from being served to another within a shared store.
* `target_id`: explicit server identity, for custom transports and in-process servers (below).
* `default_ttl_ms`: TTL applied to results that carry no `ttlMs` hint. The default `0` leaves hint-less results uncached.
* `share_public`: serve server-asserted-`"public"` entries across partitions (below). Off by default.
* `clock`: the wall-clock source, in epoch seconds. Inject one, as the example above does, and expiry tests need no sleeping.

!!! warning "Partition = verified principal"
    Derive `partition` from a **verified credential**, such as a validated token's subject. Never derive it from request-supplied data, and never from the server URL (server identity is a separate key axis). The SDK is a library with no authentication of its own: the trust anchor is whoever constructs the `CacheConfig`, which is the deployment, not the tenant. A multi-tenant gateway mints one `CacheConfig` per authenticated principal.

    The partition is also fixed for the `Client`'s lifetime. If the connection's authorization context changes mid-session (a re-authentication as a different principal, say), the cache does not follow; construct a new `Client` for the new principal.

Cache keys also carry the **server's identity**: the URL string you dialed, with any `user:pass@` userinfo stripped and otherwise byte-exact. No case folding, no query reordering, no trailing-slash cleanup. Under-normalizing only costs sharing, while over-normalizing could merge two tenants (`?tenant=a` vs `?tenant=b`), so superficially different URLs simply don't share entries. When there is no URL (an in-process server, or a `Transport` instance), the client gets a random per-instance identity instead; set `CacheConfig.target_id` to name the server (with a custom store this is required, and construction says so). The identity is sha256-hashed before it enters key material, so a URL carrying secrets in its query string never appears in store keys. Don't log the pre-hash form yourself, either.

!!! warning "`share_public` trusts the server, fleet-wide"
    By default even `"public"` entries stay within their partition. `share_public=True` serves entries the server marked `cacheScope: "public"` to **every** partition using the store, trusting the server's classification on behalf of all of them. A server that stamps `"public"` on per-tenant data (by bug or by malice) then leaks one tenant's response to the others. The flag is deliberately constructor-level only: the per-call `cache_mode` can narrow caching, but nothing per-call can widen sharing.

### What the cache never does

* **Session-tier calls bypass it.** `client.session.list_tools()` and friends always make the round trip; the cache lives on the `Client` verbs.
* **`server/discover` stays out of it.** The discover result is delivered once, at connect, and never enters the response cache, even when it carries a `ttlMs`. If you persist one yourself to skip the reconnect probe ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), its freshness is your bookkeeping: `DiscoverResult` carries `ttl_ms` and `cache_scope`, already parsed, for exactly that purpose.
* **Continuation pages are never cached.** Only cursor-less calls participate. A continuation page rejected for an expired cursor does *evict* the cached listing, because the listing changed under it.
* **Multi-round-trip reads are never cached.** A `read_resource` seeded with `input_responses`/`request_state`, or one that resolves through input rounds, never enters the cache (a spec MUST).
* **Notification eviction needs notifications.** Eviction is only as good as the transport's delivery, and the modern in-process path (`Client(server)` with the default `mode="auto"`) does not deliver standalone notifications today.
* **Eviction is eventual, not instantaneous.** Wire-path notifications are dispatched from spawned tasks, so a call racing a notification's arrival may be served the pre-eviction entry once more; the window is bounded by dispatch latency, and the eviction still lands.
* **No stale-if-error.** An expired entry is never served because the refetch failed; the error propagates.
* **No early re-fetch.** A stored entry is served until its TTL expires and the next call after that pays the round trip; nothing refreshes in the background.
* **No coalescing.** Two concurrent identical calls are two fetches.
* **No TTL beyond 24 hours.** A larger `ttlMs`, whether server-sent or configured, is clamped down on store (`mcp.client.caching.MAX_TTL_MS`), bounding how long any entry, however generously hinted, can be served.
* On a **shared store**, clients race each other. Each client drops its own write when an eviction overtook the fetch in flight, but a *co-tenant* client can still write back an entry that an eviction it never saw had removed; and that race bookkeeping is itself bounded: past 4096 tracked keys the oldest key's guard is dropped first. Both windows are accepted, and closed by the TTL cap above.
* **No serving across protocol eras.** Entries are scoped to the negotiated protocol version: on a shared persistent store, a session never serves an entry written under a different negotiated version (the same listing genuinely differs by era, since the SDK strips the 2026 fields for older sessions). Eviction likewise touches only the current era's entries; another era's entries simply age out by TTL.

### Reading the hints yourself

The hints are also plain fields on every cacheable result (`result.ttl_ms` and `result.cache_scope`, already parsed), in case you want to layer your own bookkeeping on top of (or instead of) the built-in cache.

Against an **older server** (pre-2026 protocol), the fields are simply absent from the wire, and the models show their conservative defaults: `ttl_ms == 0` and `cache_scope == "private"`, stale and unshared, the right assumption for a server that declared nothing. The cache treats a legacy session the same way: hints are never consulted there (whatever keys appear on the wire), only `default_ttl_ms` applies, and its default of `0` caches nothing, so a pre-2026 connection behaves exactly as it did before the cache existed. If you need to distinguish "the server said 0" from "the server said nothing", check `"ttl_ms" in result.model_fields_set`: it's only set when the field actually arrived.

## Older clients

Clients on pre-2026 protocol versions never see either field; the SDK strips them at serialization for those connections. Configure your hints once; there is nothing version-specific to write.

## Recap

* Six methods carry `ttlMs`/`cacheScope`; the SDK defaults them to `0`/`"private"`, stale and unshared, always safe.
* `cache_hints={method: CacheHint(...)}` at construction (both `MCPServer` and `Server`) sets server-wide values per method.
* A handler that sets the fields on its result overrides the map, per field.
* `"public"` is a promise that the result is identical for every caller. It is not access control.
* `Client` honors the hints automatically: its response cache is on by default, serves fresh entries instead of refetching, and caches nothing for servers (or sessions) that provide no hints.
* Per call, `cache_mode="refresh"` refetches and `"bypass"` skips the cache; `cache=False` at construction turns it off entirely.
