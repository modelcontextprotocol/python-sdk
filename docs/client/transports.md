# Client transports

Every `Client` talks to its server over a **transport**: the thing that actually carries the messages.

You never configure one separately. `Client` takes a single positional argument and works the transport out from its type.

The *server* side of each (what `mcp.run()` does and what you deploy) is **[Running your server](../run/index.md)**.

## Streamable HTTP

Pass a URL string and you get **Streamable HTTP**, the transport you deploy behind and the one to reach for first:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

That is the whole production client. `Client` wraps the URL in `streamable_http_client(...)` for you, on top of an `httpx2.AsyncClient` configured the way MCP needs: a 30-second timeout for connect/write/pool, and a 300-second read timeout because the server may hold a response stream open.

!!! check
    A `Client` you have constructed is **not** connected. Construction only picks the transport;
    `async with` is what opens it. Reach for the connection before entering and the SDK tells you so:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    Nothing was resolved, fetched or spawned when you wrote `Client("http://...")`. That line is free.

### Bring your own `httpx2.AsyncClient`

The moment you need an `Authorization` header, a cookie, a proxy, mTLS, or a different timeout, build the `httpx2.AsyncClient` yourself and hand it to `streamable_http_client`:

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client_transports/tutorial003.py"
```

Two things to notice:

* You own the `httpx2.AsyncClient`, so **you** enter and exit it. The SDK never closes a client it didn't create.
* `streamable_http_client(url, http_client=...)` returns a transport, and `Client(transport)` accepts it like anything else.

One TLS note: `httpx2` verifies certificates against the operating system trust store (via
[`truststore`](https://pypi.org/project/truststore/)), not a bundled CA list. In an environment with
no usable system CA store (some minimal containers), set the standard `SSL_CERT_FILE`/`SSL_CERT_DIR`
environment variables or pass an explicit `verify=ssl_context` to your `httpx2.AsyncClient`
(background in
[`httpx` and `httpx-sse` replaced by `httpx2`](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

!!! warning
    `streamable_http_client` used to take `headers=` and `timeout=` directly. It does not any more:
    its only parameters are `url`, `http_client` and `terminate_on_close`. Reach for `headers=` out
    of habit and you get:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    Everything HTTP-shaped now lives on the one `httpx2.AsyncClient` you pass in.

!!! info
    `httpx2` keeps the familiar `httpx` API, so if you know `httpx` you already know how to do auth,
    proxies, event hooks, retries and connection limits here. The SDK adds nothing on top and takes
    nothing away, except [redirect handling](#redirects). It is also where OAuth plugs in:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. That whole flow is **[OAuth clients](oauth-clients.md)**.

### Redirects

The transport connects to the URL you gave it, and only that origin.

* A `307`/`308` redirect that stays on the same scheme, host and port is followed, and so is `http://` → `https://` on the same host. That covers the usual `/mcp` → `/mcp/` trailing-slash redirect.
* A redirect anywhere else is **not** followed. The call fails with:

    ```text
    MCPError: Redirect to https://other.example.com/mcp not followed; use that URL as the endpoint if it is the intended server
    ```

    If that URL is the server you meant, put it in your config. If it isn't, the server or a proxy in front of it is misconfigured.

This holds for any `httpx2.AsyncClient` you pass in: its `follow_redirects` setting is not consulted for MCP requests, in either direction. The SDK's OAuth providers apply the same rule to their own requests.

!!! tip
    `Redirect to http://… not followed: it would downgrade this HTTPS endpoint to plain HTTP` means the
    server sits behind a TLS-terminating proxy it doesn't know about and is issuing `http://` redirects.
    That is fixed on the server (**[Deploy & scale](../run/deploy.md#behind-a-tls-terminating-proxy)**),
    or by using the exact `https://…/` URL the message suggests.

## stdio

A **stdio** server is a subprocess. The client launches it, writes JSON-RPC to its stdin and reads JSON-RPC from its stdout. It is how a desktop host runs a server on your machine: a host *is* this code plus a UI, and **[Connect to a real host](../get-started/real-host.md)** is the same relationship seen from the host's side, as a config file.

Describe the process with `StdioServerParameters` and hand it to `Client`:

```python title="client.py" hl_lines="3-7 11"
--8<-- "docs_src/client_transports/tutorial004.py"
```

Entering the block spawns the process. Leaving it shuts the subprocess down: close stdin, wait, kill if it lingers. You never clean it up yourself.

The child's stderr goes to yours. To send it somewhere else, build the transport yourself with `stdio_client` (from `mcp`) and pass that instead: `Client(stdio_client(server, errlog=log_file))`.

!!! warning
    The child does **not** inherit your environment. It gets a minimal allow-list (`HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` and `USER` on POSIX) so nothing sensitive leaks into a process you may
    not have written.

    A server that needs an API key won't find it there. Pass it explicitly with `env=`; those
    variables are merged on top of the allow-list. That is what `BOOKSHOP_API_KEY` is doing above.

## In memory

In a test there is nothing to deploy and nothing to launch. Pass the server object itself:

```python hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

No subprocess, no port, no bytes on a wire. The client and the server are two objects in the same process, and the call still goes through the real protocol layer: `search_books` is listed, validated and invoked exactly as it would be over HTTP. **[Testing](../get-started/testing.md)** builds the whole pattern around it.

The same form doubles as an embedding API: an application that constructs the server itself can call its tools without a network hop.

Closing the client cancels active in-process requests and waits for their handler cleanup before leaving application lifespan. A caller interrupted by connection closure receives `MCPError` with code `CONNECTION_CLOSED`. Handlers and callbacks must cooperate with cancellation; shielded cleanup keeps the application's resources alive until it finishes.

## SSE

`sse_client(url)`, from `mcp.client.sse`, is the HTTP transport that Streamable HTTP superseded. Wrap it the same way, `Client(sse_client("http://localhost:8000/sse"))`, to talk to a server that still speaks it, and don't build anything new on it.

## The `Transport` protocol

To `Client`, all of the above are the same thing.

A **transport** is any async context manager that yields a `(read, write)` pair of message streams: formally, the `Transport` protocol in `mcp.client`. `Client` resolves its argument by type: a `str` becomes `streamable_http_client(url)`, a `StdioServerParameters` becomes `stdio_client(params)`, a server object connects in-process, and anything else is entered as a transport directly. That last rule is why `stdio_client(...)`, `streamable_http_client(...)` and `sse_client(...)` all drop into the same slot, and why you can write your own.

### Implement a message transport

```python title="custom_transport.py"
--8<-- "docs_src/client_transports/tutorial005.py"
```

This example implements an in-memory adapter with two independent clients. A network adapter uses the same `TransportStreams` contract and replaces the memory channels with message readers and writers. You import the contract and its supporting types from `mcp.shared.transport`; the existing `mcp.client.Transport` import still works.

Each stream pair represents **one logical peer**, not an entire broker. The adapter owns framing, routing, and its network resources. The SDK owns negotiation, request correlation, and MCP validation.

Entering a transport opens its channel. Exiting stops its background tasks and closes resources it owns. The SDK also closes streams during connection shutdown, so their `aclose()` methods must be safe to call more than once. A network client supplied by the application remains owned by the application.

An inbound item is a decoded `SessionMessage` or an exception describing a recoverable message error. An exception item alone does not disconnect the peer. End the read stream on connection loss so pending calls fail instead of waiting indefinitely. Make writes cancellable and apply backpressure rather than buffering without a bound.

!!! warning "Delivery is not execution"
    MQTT or AMQP delivery guarantees do not make a tool execute exactly once. A redelivered request can repeat a side effect. Define expiry, duplicate handling, and reconnect behavior in the adapter; do not silently replay unfinished calls.

The server side of this example uses `server.serve()`. Its lifecycle and connection limits are covered under [Custom transports](../run/index.md#custom-transports). The repository's `examples/transports/README.md` contains live MQTT 5 and AMQP 0.9.1 examples, their binding rules, and the validation still needed before production use.

### Integrate a native dispatcher

```python title="dispatcher_transport.py"
--8<-- "docs_src/client_transports/tutorial006.py"
```

`DispatcherTransport` explicitly wraps an async context manager yielding a `Dispatcher`. `Client` enters that context, starts the dispatcher, and uses its ordinary MCP negotiation, callbacks, caching, and validation. It stops the dispatcher before exiting the connection context. You configure the client through the same constructor; there is no separate native client-session API.

The example uses the SDK's `DirectDispatcher`. The repository's `examples/transports/README.md` also contains a real gRPC implementation with protobuf envelopes and JSON payloads. Native network bindings implement this dispatcher boundary instead of creating `SessionMessage` streams. The connection context acquires the transport resources; it must yield an unstarted dispatcher because the SDK owns `run()`.

On the server, `runtime.connect(DispatcherTransport(...))` serves the modern per-request-envelope protocol. It rejects the legacy initialize handshake. Use `mode="auto"` or a supported modern version on the client. Message transports still support both eras. Native dispatchers supply their own contexts, so this server path rejects `session_id=` and `transport_builder=`.

!!! warning "Native bindings remain experimental"
    The custom `Dispatcher` lifecycle is still provisional pending validation against native network adapters. This wrapper is not an official gRPC wire binding. Define and test framing, cancellation, error mapping, notifications, and extension payloads in your adapter before claiming interoperability.

## Recap

* `Client("http://.../mcp")` (a URL) connects over Streamable HTTP, the production transport.
* Headers, auth, proxies and timeouts belong on an `httpx2.AsyncClient` you pass to `streamable_http_client(url, http_client=...)`. There is no `headers=` keyword.
* Redirects are followed only within the URL's own origin (a trailing-slash `307`/`308`), plus `http`→`https` on the same host. Anything else fails with `Redirect to … not followed`; configure the final URL.
* stdio is `Client(StdioServerParameters(...))`. Wrap it in `stdio_client(...)` yourself only to redirect the child's stderr.
* The subprocess gets an allow-listed environment, not yours; `env=` adds to it.
* `Client(mcp)` (the server object) connects in memory. Use it in tests, or to embed a server in the application that built it.
* A transport is anything you can `async with x as (read, write)`. `Client` hands anything that isn't a server object, a URL or `StdioServerParameters` straight to that protocol.
* Constructing a `Client` picks the transport. `async with` opens it.

Once the transport is open the two sides have to agree on a protocol version. You normally never think about it; when you do, **[Protocol versions](../protocol-versions.md)** is the page.
