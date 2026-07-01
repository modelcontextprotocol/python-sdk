# Add to an existing app

`mcp.run("streamable-http")` starts a web server for you. Sometimes you don't want that: your MCP server is one piece of a larger web application, or you already have an ASGI deployment.

For that, `mcp.streamable_http_app()` returns a **Starlette application**.

A Starlette app is an ASGI app, so anything that hosts ASGI (uvicorn, Hypercorn, another Starlette, FastAPI) can host your MCP server.

## The app

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` is an ordinary ASGI application. Hand it to any ASGI server:

```console
uvicorn server:app
```

The MCP endpoint is at `/mcp`, so a client connects to `http://127.0.0.1:8000/mcp`.

The app already carries two things:

* One route, `/mcp`: the Streamable HTTP endpoint.
* A **lifespan** that starts `mcp.session_manager`, the object that owns every live session's background work.

Run the app on its own (`uvicorn server:app`) and you never think about either.

!!! tip
    `streamable_http_app()` takes the same keyword arguments as `mcp.run("streamable-http", ...)`,
    minus `port`: the port belongs to whatever serves the app. `host` is still accepted but binds
    nothing here; the next section is what it actually controls. **[Running your server](index.md)** covers the
    options themselves.

`mcp.sse_app()` does the same for the superseded SSE transport.

## Localhost only, until you say otherwise

Out of the box the app answers **only** requests addressed to localhost. `streamable_http_app()`
cannot know which hostname it will be served behind, so it arms DNS-rebinding protection with the
safest possible allowlist; on your machine that is exactly right. Deployed behind a real hostname,
it means **every request is rejected with `421 Misdirected Request`** until you pass
`transport_security=` an allowlist of what you actually serve — and nothing you built is even
consulted first. That allowlist, and everything else between a working app and a real hostname,
is **[Deploy & scale](deploy.md)**.

## Mounting it

The moment the MCP server is *part* of a bigger application, you put the app inside a `Mount`. And the moment you do that, the lifespan becomes your problem:

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` plus the default `/mcp` path keeps the endpoint at `/mcp`. Starlette tries routes in order and `Mount("/")` matches **every** path, so your own routes go *before* it in the list. Anything after it is unreachable.
* The `lifespan` function enters `mcp.session_manager.run()` for the lifetime of the **host** app. This is the line everyone forgets.
* `mcp.session_manager` only exists *after* `streamable_http_app()` has been called. That is why the routes are built at module level and the manager is only touched inside the lifespan.

Starlette's `Host` route works the same way: swap `Mount("/", ...)` for `Host("mcp.example.com", ...)` to route by hostname instead of by path. The lifespan rule does not change, and neither does the transport-security one. A `Host("mcp.example.com", ...)` route only ever receives requests addressed to that hostname, but the transport's own Host allowlist (**[Deploy & scale](deploy.md)**) still runs first — without `"mcp.example.com"` in it, that route answers every one of them with a `421`.

!!! warning "The host app owns the lifespan"
    `streamable_http_app()` wires `session_manager.run()` into the lifespan of the Starlette it
    returns, but **a mounted sub-application's lifespan never runs**. Mount the app and that
    built-in lifespan is dead code. Whichever app sits at the top of your ASGI stack must enter
    `mcp.session_manager.run()` in its own lifespan.

!!! check
    Delete the `lifespan=lifespan` line and start the server. It starts. The route resolves.
    Then the first request to `/mcp` fails with:

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    Nothing starts the session manager except its `run()`.

## Two servers, one app

Each `MCPServer` is its own app with its own session manager. Mount as many as you like; enter every manager from the one host lifespan:

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` enters both managers; they start together and shut down in reverse order.
* The endpoints are `/notes/mcp` and `/tasks/mcp`: the mount prefix plus the default path.

## Changing the path

That trailing `/mcp` is `streamable_http_path`. Set it to `"/"` and the mount prefix becomes the whole public path:

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

Now clients connect to `/notes`, not `/notes/mcp`.

## CORS for browser clients

A browser-based client needs two permissions from you: to **send** its MCP request headers, and to **read** the one MCP sends back. Both are CORS configuration on the host app, and the transport-security allowlist above has to agree with it:

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` is the half everyone forgets. A browser **preflights** every MCP request, because `Content-Type: application/json` and the `Mcp-*` request headers are not on the CORS safelist, and a header the preflight doesn't grant is a request the browser never sends. (`allow_headers=["*"]` also works: Starlette answers a preflight with whatever it asked for.)
* `expose_headers=["Mcp-Session-Id"]` is the read half. Streamable HTTP returns the session ID in that response header, and browsers hide response headers from JavaScript unless CORS exposes them by name. Without it the client can never make its second request.
* `allow_origins` is your decision, not MCP's. Be precise, and mirror it in `allowed_origins=` above: the browser enforces CORS, but the server checks `Origin` itself, and an origin the transport doesn't trust gets a `403` even after a clean preflight.
* `allow_methods` lists the three methods Streamable HTTP uses: `POST` to send messages, `GET` to open the server-to-client stream, `DELETE` to end the session.

## Custom routes

`@mcp.custom_route()` registers a plain HTTP endpoint on the same app, for the things every deployed service needs that have nothing to do with MCP: a health check, an OAuth callback.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* The handler is plain Starlette: an `async` function from `Request` to `Response`.
* `streamable_http_app()` picks up every custom route. `app.routes` is now `/mcp` and `/health`.
* `GET /health` answers `{"status": "ok"}` with no MCP in sight.

!!! warning
    Custom routes are **never authenticated**, even when the rest of the server is. That is
    deliberate: health checks and OAuth callbacks have to be reachable before any token exists.
    Don't put anything private behind one.

## Recap

* `mcp.streamable_http_app()` returns a Starlette app with one route, `/mcp`. Any ASGI server can run it.
* Out of the box the app answers only requests addressed to localhost, and behind a real hostname it rejects everything with a `421` until you pass `transport_security=` an allowlist. **[Deploy & scale](deploy.md)** owns that, and the rest of the road to production.
* `Mount` (or `Host`) puts it inside a bigger Starlette or FastAPI app.
* **Mounting disables the built-in lifespan.** The host app's lifespan must enter `mcp.session_manager.run()`, or the first request fails.
* Several servers in one app means several mounts and one lifespan that enters every session manager.
* `streamable_http_path="/"` moves the endpoint to the mount prefix itself.
* Browser clients need CORS: `allow_headers` for the `Mcp-*` request headers, `expose_headers=["Mcp-Session-Id"]` for the response.
* `@mcp.custom_route()` adds plain, unauthenticated HTTP endpoints next to `/mcp`.

Once the server is reachable at a real URL, **[The Client](../client/index.md)** connects to it with that URL instead of a server object.
