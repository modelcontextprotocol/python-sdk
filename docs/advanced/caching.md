# Caching hints

Every result a server returns for `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` and `server/discover` carries two fields on the 2026-07-28 protocol: `ttlMs`, how many milliseconds a client may treat the result as fresh, and `cacheScope`, whether a cached result may be shared across users (`"public"`) or belongs to one authorization context (`"private"`).

The server doesn't cache anything. The fields are a *declaration*: "this tool list is the same for everyone and won't change for a minute." A client (or a gateway in front of you) may then skip the round trip. Honoring the hints is the client's choice; emitting them is the server's job, and the SDK does it for you.

Out of the box every result says `ttlMs: 0, cacheScope: "private"` — immediately stale, never shared. That is always safe and always conformant. If your lists really are stable and identical for all callers, say so at construction:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* The map is keyed by **method name** — the six cacheable methods are the only legal keys. The parameter is typed `Mapping[CacheableMethod, CacheHint]`, so your editor autocompletes the keys and flags a typo before you run; anything that slips past the type checker raises at construction.
* A method you don't mention keeps the defaults. The map is a set of overrides, not a manifest.
* `CacheHint(ttl_ms=5_000)` left `scope` unset, so it stays `"private"`: five seconds of freshness, per caller. Scope and TTL are independent decisions.
* `"server/discover"` is a legal key too — the handshake result is cacheable like any list.

!!! warning
    `cacheScope: "public"` means *anyone* may be served your cached response — a shared
    gateway will happily hand one user's result to another, even when the request was
    authenticated. Mark a result `"public"` only when it is identical for every caller, and
    never use `cacheScope` as access control: it is a label, not a lock.

## Per-handler override

On the low-level `Server`, handlers build their results by hand — and `ttl_ms` / `cache_scope` are just fields on the result models. A handler that sets them explicitly always wins over the constructor map, field by field:

```python title="server.py" hl_lines="11 17"
--8<-- "docs_src/caching/tutorial002.py"
```

The handler said `ttl_ms=1_000` and nothing about scope. On the wire: `ttlMs: 1000` (the handler's, not the map's `60_000`) and `cacheScope: "public"` (the map's — the handler left it unset). Explicit beats configured, configured beats default — per field, so a handler can pin one field and leave the other to the server-wide policy.

This is also the escape hatch for dynamics the constructor can't know: a handler that filters `resources/read` per user can return `cache_scope="private"` for one URI from an otherwise-public server.

One caveat on paginated lists: the protocol requires the **same `cacheScope` on every page** of one list. The constructor map satisfies that by construction — it's keyed by method, not by page. But a handler that overrides the scope itself owns that consistency: override it on *every* page, never only when a cursor is present, or page one and page two will disagree.

## What the client sees

On the client, the hints arrive as plain fields on every cacheable result — `ttl_ms` and `cache_scope`, already parsed:

```python title="client.py" hl_lines="15"
--8<-- "docs_src/caching/tutorial003.py"
```

The SDK parses; it does not (yet) act. There is no built-in response cache: calling `list_tools()` twice makes two round trips, whatever the TTL said. The spec makes honoring optional — a client that ignores the hints entirely is fully conformant — so until the SDK grows a response cache, the supported path is to read the fields and do your own bookkeeping:

* **Freshness** is `now < t_received + ttl_ms / 1000`: record the clock when the response arrives, and treat the result as reusable until the TTL runs out. `ttl_ms == 0` means *immediately stale* — don't reuse it at all.
* **Scope is a sharing rule, not a suggestion.** A `"private"` result may be reused only within the same authorization context — same access token, same cache. Never put `"private"` results in a cache shared across users.
* **Notifications beat TTL.** If the server sends `list_changed` while your copy is still fresh, the copy is stale now — re-fetch.

Against an **older server** (pre-2026 protocol), the fields are simply absent from the wire, and the models show their conservative defaults: `ttl_ms == 0`, `cache_scope == "private"` — stale and unshared, the right assumption for a server that declared nothing. If you need to distinguish "the server said 0" from "the server said nothing", check `"ttl_ms" in result.model_fields_set`: it's only set when the field actually arrived.

## Older clients

Clients on pre-2026 protocol versions never see either field — the SDK strips them at serialization for those connections. Configure your hints once; there is nothing version-specific to write.

## Recap

* Six methods carry `ttlMs`/`cacheScope`; the SDK defaults them to `0`/`"private"` — stale and unshared, always safe.
* `cache_hints={method: CacheHint(...)}` at construction (both `MCPServer` and `Server`) sets server-wide values per method.
* A handler that sets the fields on its result overrides the map, per field.
* `"public"` is a promise that the result is identical for every caller. It is not access control.
* Clients read the hints as `result.ttl_ms` / `result.cache_scope` and own the caching decision themselves — the SDK has no built-in response cache yet.
