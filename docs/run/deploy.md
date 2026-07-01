# Deploy & scale

Your server works. Now it needs a real hostname, and more than one worker behind it.

Almost none of that is MCP's business. You bring the ASGI server, the process manager, the load balancer. What this page has is the short list of things that *are* MCP's business: one setting that gates every deployment, and the two places where "more than one worker" changes what the SDK does.

## Before anything else: the Host allowlist

`streamable_http_app()` cannot know which hostname it will be served behind, so it assumes the safest answer: localhost. With no `transport_security=`, the app switches on **DNS-rebinding protection** and accepts a request only if its `Host` header is `127.0.0.1:<port>`, `localhost:<port>`, or `[::1]:<port>`. The `Origin` header, when there is one, has to be the `http://` form of the same. On your machine that is exactly right: it stops a malicious web page from driving your local server through a DNS name it rebound to `127.0.0.1`.

Deployed behind a real hostname, that same default rejects **every request** until you say otherwise. The check runs before anything MCP-shaped does, so nothing you built is even consulted:

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

`transport_security=` is the fix. Allowlist what you actually serve:

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* `allowed_hosts` entries are exact strings: `"mcp.example.com"` matches a bare `Host` header and `"mcp.example.com:*"` matches any port. List both.
* `allowed_origins` only matters for browsers, because nothing else sends `Origin`. It is the server-side twin of the CORS configuration in **[Add to an existing app](asgi.md)**.
* Behind a reverse proxy that already controls the `Host` header, switching the check off is the honest configuration: `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.
* Passing a non-localhost `host=` (for example `host="mcp.example.com"`) does **not** allowlist that hostname. It only stops the localhost default from arming the protection, which leaves every Host and Origin accepted. Say what you mean with `transport_security=` instead.

!!! check
    Delete the `transport_security=security` argument and deploy the app anyway. It starts, `/mcp`
    routes, and every request (including from a plain `curl`) comes back:

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    You will not find those words on the client side. A `421` is a plain-text HTTP response, not a
    JSON-RPC error, so the MCP client raises a generic transport error; the hostname it
    didn't like appears only in the **server's** log, as a single warning. A freshly
    deployed server that refuses every connection is a Host allowlist until proven otherwise.
    **[Troubleshooting](../troubleshooting.md)** starts here too.

## Workers, and who has to be sticky

Once the hostname answers, put more than one worker behind it. There is no SDK knob for that; you scale a Starlette app the way you scale any ASGI app, by handing the object to something that knows how to fork:

```console
uvicorn server:app --workers 4
```

Four processes, one socket. And now the question every deployment has to answer: **does a request have to reach the worker that saw the last one?**

For a client speaking the **2026-07-28** protocol, no. A modern request is one self-contained POST: no `initialize` handshake before it, no `Mcp-Session-Id` on the response, nothing for a second request to come back *to*. Route it to any worker.

That is not a mode you switch on. `stateless_http=True` looks like it should be, but the transport routes on the `MCP-Protocol-Version` request header, hands a modern request to the modern handler, and **returns**. The line that reads `stateless_http` comes *after* that return. It isn't that the flag is ignored on the 2026-07-28 path; it is never reached. `stateless_http` is a knob for the **legacy** leg only, and the modern path is sessionless by construction.

For a legacy client on spec version 2025-11-25 or earlier, the answer depends on that flag:

| Client's protocol version | Session | What the load balancer must do |
| --- | --- | --- |
| **2026-07-28** | None. `Mcp-Session-Id` is never set. | Nothing. Any worker serves any request. |
| **2025-11-25 and earlier** (the default) | `Mcp-Session-Id`, held in one worker's memory. | **Sticky sessions.** A follow-up that reaches a different worker gets a `404` *"Session not found"*. |
| **2025-11-25 and earlier**, with `stateless_http=True` | None. | Nothing. The cost is the server-to-client back-channel (sampling, push elicitation, `roots/list`) and resumability. |

Sticky sessions and what the legacy leg costs are their own page, **[Serving legacy clients](legacy-clients.md)**; the two eras themselves are **[Protocol versions](../protocol-versions.md)**. What matters here is the shape of the answer: *on 2026-07-28 you are already stateless, with nothing to configure.*

The rest of this page is the two things that being stateless does **not** buy you.

## `requestState` across workers

A **[multi-round-trip](../handlers/multi-round-trip.md)** tool needs something the client has to go get (a confirmation, a choice, a credential), so it returns a question instead of an answer and finishes on the retry. Between the two rounds the client holds an opaque `request_state` token the server minted. On the retry the server has to open that token again.

*Sealed under what key?* By default, one the server generated with `os.urandom(32)` at construction time. Under `--workers 4` that is four constructions, in four processes: four different keys, never written anywhere, never shared, gone on restart.

Here is a tool that asks before it acts, on a server that configures nothing:

```python title="server.py" hl_lines="15 21"
--8<-- "docs_src/deploy/tutorial002.py"
```

The first round reaches worker A. Worker A seals `refund:120` under **its** key and returns the token. The client puts the question in front of a person, gets a yes, and retries. The retry is a brand-new HTTP request.

!!! check
    Let that retry reach worker B. B tries to unseal a token it did not mint, cannot, and refuses the
    whole round. `refund` is never called; the client gets a JSON-RPC error:

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    That message is **frozen**. Expired, tampered with, replayed against different arguments, or (by
    far the most common cause in a real deployment) sealed by a sibling worker: the client is told
    the same thing every time, so the wire never reveals which check failed. The real reason is one
    `WARNING` in the server's log:

    ```text
    requestState rejected on tools/call: unknown key
    ```

    A multi-round-trip tool that worked with one worker and started failing *some of the time* at
    two is this. Both rounds still have to reach the same process, so it fails exactly as often as
    your load balancer separates them.

The two rounds are two independent HTTP requests, and several ordinary things separate them: a proxy that balances per request, a connection that dropped in between, a deploy or a restart, a client that persisted `request_state` and is resuming from a different process entirely (**[Driving the loop yourself](../handlers/multi-round-trip.md#driving-the-loop-yourself)**). Any of them is "a different worker".

The fix is one argument. It has **two** halves.

```python title="server.py" hl_lines="3 13 15"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** is the half everyone finds. Give every instance the same secret (at least 32 bytes of it), and every instance can unseal what any sibling minted. `keys[0]` seals and every key in the list unseals, which is the rotation ring; **[Rotating keys](../handlers/multi-round-trip.md#rotating-keys)** is how you turn it without downtime.
* **The server's name** is the half almost nobody finds, and the reason cross-instance retries still fail after you share the key. Every sealed token carries the server's `name` as an **audience claim**, checked strictly on the way back in. Two instances built from the same code have the same name and never notice it. Name them apart (`MCPServer(f"billing-{POD}")` reads like good observability hygiene), and every cross-instance retry is refused exactly as above, shared key or not. The log says `audience` instead of `unknown key`; the client cannot tell the difference.

Mint the secret once and hand the same value to every instance. This is the command the SDK's own error message tells you to run if you pass it fewer than 32 bytes:

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "Same keys, *and* the same name"
    A multi-instance deployment must share both. If per-instance names are load-bearing for you,
    give the fleet one explicit audience instead: `RequestStateSecurity(keys=[...], audience="billing")`.
    Every instance then mints and accepts under `"billing"` no matter what it is called.

Everything else about the seal is **[Protecting `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**: what it binds, the per-round `ttl` (600 seconds by default), bringing your own codec, why the unconfigured default is exactly right on `stdio`. This page's whole contribution is a two-item checklist: *same keys, same name.*

!!! info
    You are on this path even if you have never typed `InputRequiredResult`. A tool whose parameters
    use `Resolve(...)` (**[Dependencies](../handlers/dependencies.md)**) is a multi-round-trip tool,
    and the SDK mints and seals its `request_state` for it. Same default key, same failure across
    workers, same fix.

## Change notifications across replicas

A client's `subscriptions/listen` stream is one long-lived response, so it is pinned to one replica for its whole life. A `ctx.notify_resource_updated(...)` published on a **different** replica has to reach it.

The seam between the two is the `SubscriptionBus`. Whatever bus you give a server is the one every publish goes into and every open stream listens on, so hand the same bus to every replica:

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

Nothing about the fan-out cares which server object a stream is attached to. Two servers holding one `InMemorySubscriptionBus` already behave this way: open a listen stream on one, `edit_note` on the other, and the stream hears about it. That in-memory bus only spans server objects inside one process, which makes it the model, not the deployment:

* Across real processes, **the SDK ships no bus that can help you.** `SubscriptionBus` is a two-method `Protocol` (`publish` and `subscribe`) that you implement over your own pub/sub backend (Redis, NATS, whatever you already run) and pass as `MCPServer(subscriptions=...)`. **[Subscriptions](../handlers/subscriptions.md#one-process-is-the-default-more-takes-a-bus)** has the sketch and the contract.
* The bus carries four small typed events, never JSON-RPC. Acknowledgment, filtering, and stream lifecycle stay in the SDK, so your bus cannot break the protocol; it can only move events between processes.
* Streams are **not** resumable and events are **not** replayed. Losing a replica drops its streams; the clients re-listen and re-fetch. There is no event store to share and nothing else to configure. This is the one place where scaling out is genuinely just more of the same.

## What the SDK does not give you

An `MCPServer` is a protocol implementation, not an application server. The deployment knobs you go looking for next are missing on purpose:

* **No `workers=`.** `mcp.run("streamable-http")` starts exactly one uvicorn process, and that is all it will ever start. Multi-process is `streamable_http_app()` handed to whatever you already deploy ASGI with: `uvicorn --workers`, gunicorn, your platform's process manager. This page is deliberately not a tutorial for any of them; their documentation is better than a copy of it here would be.
* **No health-check route.** `@mcp.custom_route("/health", methods=["GET"])` is the whole answer, and it is never authenticated even when the rest of the server is. That is right for a liveness probe, wrong for anything private. **[Add to an existing app](asgi.md#custom-routes)** shows one.
* **No production settings object.** There is nowhere on `MCPServer` to write down timeouts, TLS, graceful shutdown, or connection limits, because none of those are its job. They belong to your ASGI server, and you configure them there. **[Running your server](index.md)** covers the handful of settings the constructor *does* take.
* **No shipped `EventStore`, and on 2026-07-28 no use for one.** Resumability is a feature of the legacy stateful leg; a modern exchange is one POST, one response, and nothing to resume.

## Recap

* Out of the box the app answers only requests addressed to localhost. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` is the go-live gate: until you pass it, every request behind a real hostname is a `421` and the reason is only in the server's log.
* On 2026-07-28 there is no session and nothing for a load balancer to be sticky on. `stateless_http=True` is a legacy-only knob because a modern request is routed and answered before that flag is ever read.
* The default `requestState` key is `os.urandom(32)`, minted per process. A multi-round-trip retry that reaches a different worker fails with `-32602` *"Invalid or expired requestState"*.
* The fix is `RequestStateSecurity(keys=[...])` **and** the same server name on every instance. The name is the token's default audience claim. Same keys, same name.
* Change notifications cross replicas through one shared `SubscriptionBus`. The SDK's only implementation is in-process; the two-method `Protocol` over your own pub/sub is yours to write.
* There is no `workers=`, no health route, no production settings object. Bring your own ASGI server.

The other thing a real hostname needs in front of it is a token: **[Authorization](authorization.md)**.
