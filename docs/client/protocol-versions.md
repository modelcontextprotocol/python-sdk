# Protocol versions

MCP has two eras.

Servers released before 2026-07-28 open every connection with the **`initialize` handshake**: the client proposes a version, the server counters, the client acknowledges — all before the first useful request. Servers at **2026-07-28** drop the handshake. The client sends one **`server/discover`** probe and the server answers it with everything in a single result.

You haven't had to care, because `Client` negotiates for you. This chapter is about the one constructor argument that controls it — `mode=` — and the three times you change it.

## `mode="auto"`

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

You didn't pass `mode`, so you got the default: `"auto"`. Entering `async with` sends a single `server/discover` probe at the newest version this SDK speaks. Then:

* A **modern server** answers it. The client adopts the result. One round trip, done.
* An **older server** has never heard of `server/discover` and returns an error. The client falls back to the classic `initialize` handshake and takes whatever that negotiates.

Either way you come out connected, and `client.protocol_version` tells you which it was:

```text
2026-07-28
```

That is the whole feature. One `Client`, any era of server, no branching in your code.

!!! info
    `MCPServer` answers `server/discover`, so against your own in-memory server `auto` always lands
    on `2026-07-28`. The fallback only ever fires against a real pre-2026 server — which is exactly
    when you want it to.

## `mode="legacy"`

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` never probes. It runs the `initialize` handshake — the same connection a pre-2026 client opens.

```text
2025-11-25
```

Same server. It speaks `2026-07-28` perfectly well — you told the client not to ask.

You want this for the **push-style** features.

A server-initiated request is the server calling *you*: `ctx.elicit(...)` putting a form in front of your user, sampling asking your model for a completion mid-tool-call. That channel only exists on a handshake-era session.

At 2026-07-28 it is gone. The server *returns* its questions and you retry the call with the answers (**Multi-round-trip requests**).

`mode="auto"` only gives you a handshake when the server is too old for anything else. `mode="legacy"` guarantees one. Reach for it whenever you hand `Client(...)` a `sampling_callback`, an `elicitation_callback` you want driven as a request, or a `message_handler` — **Client callbacks** goes through each.

## Pinning a version

`mode` also accepts a modern protocol version string. Today that set is exactly `["2026-07-28"]`.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

A pin sends **nothing**. No probe, no handshake. The client adopts `2026-07-28` locally and the connection is live the instant `async with` returns.

A pin is a promise *you* make: you already know the server speaks that version. The client doesn't check.

!!! check
    A pin is not a discovery. Print `client.server_info` and the price is right there:

    ```text
    name='' title=None version='' description=None website_url=None icons=None
    ```

    The client never asked the server who it is, so `server_info` is a blank. `client.server_capabilities`
    is the same story — every capability is `None`. Tool calls still work (the protocol needs none of it);
    code that reads `server_capabilities` to decide what to offer does not.

    The next section is the fix.

Only modern versions are pinnable. A handshake-era string is rejected at construction, before any I/O, and the error tells you what to write instead:

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version — use mode='legacy')
```

## Reconnecting with `prior_discover`

The probe is cheap, but it is still a round trip you pay on every reconnect — and the answer almost never changes.

So keep it. After an `auto` connection, `client.session.discover_result` holds the exact `DiscoverResult` the server sent: its `supported_versions`, its `capabilities`, its `server_info`, its `instructions`. Hand it back as `prior_discover=` the next time:

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

The second connection made **zero** negotiation round trips and still knows exactly who it is talking to. That is the pinned mode done properly: `mode=` names the version, `prior_discover=` supplies the identity. ✨

`DiscoverResult` is a Pydantic model. `saved.model_dump_json()` goes into a file or a cache; `DiscoverResult.model_validate_json(...)` brings it back in the next process.

!!! tip
    `prior_discover=` only does anything when `mode` is a version pin. Under `"auto"` the client
    probes the server anyway, and under `"legacy"` it is ignored.

## The four modes

| You write | Negotiation traffic | You get |
| --- | --- | --- |
| `Client(target)` | one `server/discover` probe; the `initialize` handshake if it fails | the newest version both sides speak, whichever era |
| `Client(target, mode="legacy")` | the `initialize` handshake | a handshake-era version; server-initiated requests work |
| `Client(target, mode="2026-07-28")` | none | that version, pinned — with a blank `server_info` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | none | that version, pinned — *and* the identity you saved last time |

## Recap

* MCP has a handshake era (up to `2025-11-25`, the `initialize` handshake) and a modern era (`2026-07-28`, `server/discover`). `Client` bridges them.
* `mode="auto"` is the default: probe, fall back. Leave it alone unless one of the other three rows describes you.
* `client.protocol_version` is always the answer to "what did I get?".
* `mode="legacy"` forces the handshake. It is what you need for server-initiated requests — sampling, push elicitation, `message_handler`.
* A version pin (`mode="2026-07-28"`) sends no negotiation traffic at all, at the cost of a blank `server_info`.
* `prior_discover=` pays that cost back: save `client.session.discover_result`, reconnect with it, get both.

A modern connection has no push channel — so how does a 2026 server ask you a question mid-call? It returns it: **Multi-round-trip requests**.
