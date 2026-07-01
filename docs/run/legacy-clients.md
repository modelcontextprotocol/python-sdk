# Serving legacy clients

MCP has two protocol eras: the `initialize`-handshake era, up to spec version `2025-11-25`, and the modern era, `2026-07-28`. **[Protocol versions](../protocol-versions.md)** is the page on the split itself.

This page is about the server side of that split, and the answer fits in one sentence: **the `streamable_http_app()` you already deploy serves both.**

The SDK routes every request by its `MCP-Protocol-Version` header. A request naming `2026-07-28` goes to the modern handler. A request naming a handshake-era version, or carrying no header at all (which is how a pre-2026 client's `initialize` arrives), goes to the transport those clients expect: `initialize` handshake, sessions and all. It happens per request, before your code, on the one app.

So a legacy client is not something you build *for*. It is something that connects *to* the server you already wrote. You configure nothing.

!!! note
    Nothing, literally. There is no `legacy=` option, no version allowlist, no way to reject or
    disable an era — not on `streamable_http_app()`, not on `run()`, not on the session manager.
    Both eras are always on. The nearest thing to a per-era switch in that signature is
    `stateless_http`, and it is most of this page.

## One handler, both eras

Here is a tool that has to ask the user something, and both eras of client calling it:

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` needs one thing the model didn't supply: how many copies. `Annotated[..., Resolve(ask_quantity)]` is how a tool declares that (**[Dependencies](../handlers/dependencies.md)** is that whole story). Nothing in `reserve` names a version, checks a capability, or branches.

The two clients are open **at the same time**, on the same `mcp` object. `mode="legacy"` runs the `initialize` handshake — the exact connection a pre-2026 client opens. The other one takes the default and lands on `2026-07-28`.

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

Same server, same handler, same answer. That is the whole feature.

It is worth pausing on *how*, because the two clients were asked the same question over two completely different wires. The `2026-07-28` connection has no channel for the server to send a request on, so `Resolve` returned the question inside the tool result and the client retried the call with the answer (**[Multi-round-trip requests](../handlers/multi-round-trip.md)**). The `2025-11-25` connection has no such thing; there, `Resolve` sent a live `elicitation/create` request mid-call and waited. You wrote neither. `Resolve` reads the connection's negotiated version and picks; your tool body sees an `AcceptedElicitation` either way.

!!! tip
    That era-portability is *why* `Resolve` is the API to build on. Its older sibling `ctx.elicit()`
    (**[Elicitation](../handlers/elicitation.md)**) only ever sends `elicitation/create`, so it only
    ever works on a legacy connection — on a `2026-07-28` one the call fails. If a tool still uses
    it, the fix is the one you see above, not a version check.

## What a legacy session costs you

The routing is free. The session is not.

A `2026-07-28` connection is **sessionless**: every request stands alone, and the modern handler never issues an `Mcp-Session-Id`. A legacy connection is the opposite. The moment a pre-2026 client sends `initialize`, the SDK mints an `Mcp-Session-Id`, returns it in a response header, and keeps a live record behind it for the client's later requests to find: the negotiated version, the open streams, a background task driving the session.

That record is a **plain in-process `dict`**. There is no distributed session store and no way to plug one in.

On one worker that is invisible. On two, it is the whole problem: a request that carries an `Mcp-Session-Id` and lands on a worker that didn't mint it finds nothing in that dict, and the answer is a `404` — `Session not found` — not the tool result. So the moment you run more than one worker, **legacy clients need sticky routing**: every request in a session has to reach the process that started it. Modern clients never do; they have no session to be sticky to. **[Deploy & scale](deploy.md)** covers stickiness and everything else about running more than one of these.

!!! warning
    `event_store=` looks like the fix and is not. It is **resumability** — replaying missed SSE
    events to a client reconnecting to the *same* session — not a session store. It never makes a
    session reachable from another process.

## The one knob: `stateless_http`

If stickiness is a cost you refuse to pay, there is exactly one thing you can change.

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

That is the server from the top of the page plus one keyword. `stateless_http=True` makes the legacy leg build a throwaway, per-request session instead: no `Mcp-Session-Id` issued, nothing remembered between requests, so any worker can serve any request and the load balancer can do whatever it likes.

Two things about it matter more than what it does.

**It only touches the legacy leg.** Requests are routed on the version header *before* `stateless_http` is read, so the modern path never sees it. A `2026-07-28` connection is already sessionless and is exactly the same under either value.

**It costs both server-to-client channels on that leg.** A session that lives for one `POST` has no stream for the server to push a request down and no standalone stream for it to push notifications down. Every server-initiated request raises `NoBackChannelError`: `ctx.elicit()`, the retired sampling and roots calls (**[Deprecated features](../deprecated.md)**), and — yes — `Resolve` asking a *legacy* client its question. Notifications don't even get an error; they are silently dropped.

!!! check
    Do the wrong thing. `reserve` is the exact tool that just served both clients. Deploy it with
    `stateless_http=True`, connect the same two clients over HTTP, and call it from each.

    The modern client still gets `Reserved 2 of 'Dune'.` — the modern leg didn't change.

    The legacy client's call does not come back as an `is_error` result the model could read.
    The whole request fails, as a top-level protocol error:

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` did not save you. On a `2025-11-25` connection it *has* to send `elicitation/create`,
    and the channel it needs is exactly the thing `stateless_http=True` gave away. Era-portable
    code is not back-channel-free code.

So it is a real trade, and it only exists on the legacy leg: **sessionful and sticky, or stateless and one-directional.** If your tools never call back into the client, `stateless_http=True` is free and you should take it. If they do, keep the sessions and keep the routing sticky.

## Where your code actually forks

Almost nowhere.

Tools, resources, prompts, structured output, progress, errors: none of them care which era called. The `initialize` handshake, the `Mcp-Session-Id`, the standalone stream, the `DELETE` that ends a session — the SDK owns all of it, and a handler never sees any of it. Interactive input is *the* place the eras genuinely differ on the wire, and `Resolve` exists so that it is not your problem: you just watched one tool serve both.

There is exactly one thing left, and it is **change notifications**, because the two eras listen on different pipes:

* A `2026-07-28` client opens a `subscriptions/listen` stream and reads the subscriptions bus. `ctx.notify_resource_updated()` — and `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()` — publish there, and *only* there. **[Subscriptions](../handlers/subscriptions.md)** is that page.
* A legacy client reads the standalone stream its session keeps open. `ctx.session.send_resource_updated()` — and `send_tool_list_changed()` and friends — write to the *connection* that carried the request: for a legacy session, that is its standalone stream. For a modern HTTP request there is no such channel, and the notification is quietly dropped.

Over HTTP, neither call reaches the other era's clients. To tell everyone, call both:

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

Two lines, no `if`, no version check, and you are done. That is the entire list of things a handler does differently because a legacy client exists.

## Recap

* One `streamable_http_app()` serves both protocol eras. The SDK routes each request by its `MCP-Protocol-Version` header; there is nothing to configure and no era knob to look for.
* A legacy client costs you a session: an in-process `Mcp-Session-Id` record with no distributed store behind it. More than one worker means **sticky routing**, or the wrong worker answers `404 Session not found`. **[Deploy & scale](deploy.md)** has the multi-worker story.
* `stateless_http=True` is the one knob, and it is **legacy-leg-only**. It buys free load balancing for legacy clients at the price of both server-to-client channels on that leg: server-initiated requests raise `NoBackChannelError` (a top-level error at the client, not an `is_error` result), and notifications are dropped.
* A `2026-07-28` connection is sessionless either way. `stateless_http` never touches it.
* Your handler code forks on era in exactly one place: change notifications. `ctx.notify_*` reaches `subscriptions/listen` clients; `ctx.session.send_*` reaches legacy sessions. Call both.
* Everything else — including asking the user for input, via `Resolve` — is era-portable by construction. Write the modern thing once.
