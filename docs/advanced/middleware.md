# Middleware

A **middleware** is one async function that wraps every message your server receives.

You write it as `async (ctx, call_next)` and append it to `server.middleware`. That is the whole API.

!!! warning
    `Server.middleware` is marked **provisional** in the source. The signature and semantics are
    expected to change before v2 is final. Use it to *observe* — timing, logging, tracing.
    Do not make it the foundation your server stands on.

This is a **low-level `Server`** feature. `MCPServer` does not expose a middleware list.
If `Server(name, on_call_tool=...)` is new to you, read **The low-level Server** first.

## A timing middleware

One server, one tool, one middleware that logs how long each message took:

```python title="server.py" hl_lines="40-46 50"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` is the same `ServerRequestContext` your handlers receive. `ctx.method` is the raw
  method string; `ctx.params` are the raw params, **before** any validation.
* `call_next(ctx)` runs the rest of the chain — validation, the handler lookup, your handler.
  Return what it returned and the response is untouched.
* The `try`/`finally` is deliberate: a handler that raises is still timed, because the failure
  reaches your middleware as the exception out of `call_next`.
* `server.middleware.append(...)` registers it. The list runs outermost-first, so
  `middleware[0]` is the one closest to the wire.

### Check it

Connect a client, list the tools, call one. Your log has **three** lines:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

You made two calls and got three lines. The first is `server/discover` — the request the
client sent to set the connection up, before you asked for anything.

That is the point. Middleware wraps **every** inbound message:

* The connection setup — `server/discover`, or `initialize` and `notifications/initialized`
  on a legacy session.
* Every request and every notification. For a notification, `ctx.request_id is None`,
  `call_next(ctx)` returns `None`, and whatever you return is discarded.
* Even a method the server has no handler for: `call_next` raises the
  `MCPError(-32601, "Method not found")` *through* your middleware on its way to the client.

## What you can do inside one

In increasing order of how much you should hesitate:

* **Observe.** Time it, count it, log it. The example above.
* **Refuse.** Raise an `MCPError` *instead of* calling `call_next(ctx)` and that one message is
  answered with a JSON-RPC error. The connection stays up; the next message goes through.
* **Rewrite.** `ctx` is a dataclass — `await call_next(dataclasses.replace(ctx, params=...))`
  hands the rest of the chain different params than the client sent. Never do this to
  `initialize`: the result the client gets back is built from your rewritten params, but the
  server commits its connection state from the original wire params — the two sides can finish
  the handshake disagreeing about what they negotiated.

!!! check
    `initialize` is one of the things middleware wraps — and it is the *only* hook you get
    for it. Try to take it over with `add_request_handler` and the SDK refuses:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` is handled inline: the server reads no further inbound messages until your
    middleware chain returns. Awaiting a server→client request (`ctx.session.send_request(...)`,
    an elicitation) while handling `initialize` therefore **deadlocks the connection** — the
    response you are waiting for can never be read. Fire-and-forget notifications are fine.

## `OpenTelemetryMiddleware`

The SDK ships one middleware: `OpenTelemetryMiddleware`. Construct it and append it —
`server.middleware.append(OpenTelemetryMiddleware())` — exactly the line you already wrote
for `log_timing`.

Every inbound message becomes a `SERVER` span named after the method and its target, so a
`tools/call` for `search_books` is the span `tools/call search_books`.

* Every span carries `mcp.method.name` and `mcp.protocol.version`; a request's span also
  carries its JSON-RPC request id (a notification has none).
* A `tools/call` span gets OpenTelemetry's GenAI semantic conventions —
  `gen_ai.operation.name` (`"execute_tool"`) and `gen_ai.tool.name` — so a tracing UI groups
  your tool calls the way it groups any other agent's. A `prompts/get` span gets
  `gen_ai.prompt.name`. The list methods carry no `gen_ai.*` keys.
* A handler that raises sets the span's status to error. So does a tool result with
  `is_error=True`.

!!! tip
    The SDK depends only on `opentelemetry-api`. With no exporter installed those spans are
    no-ops, so appending this middleware costs you nothing. Install `opentelemetry-sdk` plus an
    exporter and everything lights up — no server change.

The import is the catch. The class lives at `from mcp.server._otel import OpenTelemetryMiddleware`
today, and the leading underscore is not an accident: it is the same provisional flag this whole
page opened with. The SDK has not given it a public spelling yet, so the import path is the one
line here you should expect to change.

!!! info
    If you have written ASGI middleware, you already know this shape. Starlette's
    `(scope, receive, send)` became `(ctx, call_next)`, and it runs *after* the transport, on
    the decoded message instead of the raw HTTP request. The two compose: Starlette middleware
    on `streamable_http_app()` sees HTTP; this sees MCP.

## Recap

* A middleware is `async (ctx, call_next) -> result`, appended to `server.middleware` on the
  low-level `Server`.
* It wraps **every** inbound message — `server/discover`, `initialize`, requests, notifications,
  unknown methods — and runs outermost-first.
* `ctx.request_id is None` is how you tell a notification from a request.
* Raise instead of calling `call_next` to refuse one message; the connection survives.
* `OpenTelemetryMiddleware` turns each message into a span — with GenAI attributes on tool
  calls and prompt gets — for the price of one `append`, and costs nothing until you install
  an exporter.
* The whole surface is provisional. Observe with it; don't build on it.

That is everything that wraps a request. **Authorization** is what decides whether the request
gets to run at all.
