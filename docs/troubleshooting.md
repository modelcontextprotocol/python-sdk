# Troubleshooting

Every heading on this page is the exact text of an error the SDK produces, followed by what it means and the one-move fix. Find the last line of your traceback (or your server log) here with your browser's find-in-page, and read only that entry.

Several entries run against this one server. One tool and one templated resource, each raising for a city it doesn't know:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

The errors this page quotes are real: the SDK's own test suite reproduces every one of them.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`

This is not an MCP error. It is anyio noise, and your real error is the **last line** of the paste.

`Client.__aenter__` starts a task group. anyio wraps anything that leaves a task group in an `ExceptionGroup`, so *every* exception that escapes an `async with Client(...)` block, whatever it is, arrives inside one:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

Two things to do with that:

1. **Read the bottom.** `MCPError: No forecast for 'Atlantis'.` is the failure; find *its* text on this page.
2. **Catch inside the block.** The `ExceptionGroup` only appears when the exception *leaves* the `async with`. Caught inside it, the same failure is the plain `MCPError`, no group anywhere:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    A failure during *connection* (a wrong URL, a server that isn't running, the `421` further
    down this page) escapes from `async with` itself, so there is no "inside" to catch it in.
    For those, read the bottom of the group.

## `RuntimeError: Client must be used within an async context manager`

`Client(...)` only builds the object. Nothing connects until `async with`, so every method refuses:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Enter it. `__aenter__` is the connection:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` is the disconnection, which is why there is no `client.close()` to forget. **[Testing](get-started/testing.md)** is built on exactly this pattern.

## `Error executing tool <name>: <message>` and `Unknown tool: <name>`

You are reading a **result**, not an exception. `call_tool` did not raise, and it never will for a failing tool.

Call `forecast` for a city the server doesn't know, and the exception it raises comes back with the request marked as *succeeded*:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` is the same shape for a name the server never registered, and a bad argument is rejected the same way, against the tool's input schema, before your function ever runs.

The fix is in your client: **check `result.is_error`**. A `try/except` around `call_tool` catches none of these, because there is nothing to catch. This is deliberate, and it is the single most useful thing on this page to internalise: the *model* chose the call, so the model gets the message and a chance to try again. **[Handling errors](servers/handling-errors.md)** is the whole story, including the `MCPError` path that *does* raise.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool`

You wrote `@mcp.tool` instead of `@mcp.tool()`. `tool()` is a decorator *factory*: without the parentheses, Python hands your function to its `name=` parameter.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Add the parentheses. `@mcp.resource(...)` and `@mcp.prompt()` say the same thing for the same slip.

!!! note
    This raises when the module is **imported**, before any client connects. So a host that shows
    your server as *failed to start* (or *disconnected*), rather than as connected with zero
    tools, has this shape: run `python server.py` yourself and read the traceback. A type checker
    also catches it: a function is not a valid `name=`.

## `Tool already exists: <name>`

Two registrations used the same tool name. The **first** one wins, the second is silently dropped, and this warning in the *server log* is the only signal:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` reports one `forecast`, and it is `forecast_today`. Rename one of them. `MCPServer(..., warn_on_duplicate_tools=False)` silences the warning without changing the outcome, so leave it on. Resources and prompts have the same rule and the same log line (`Resource already exists:`, `Prompt already exists:`).

## My host lists zero tools

There is no error string for this, which is exactly why it is hard to search. The SDK never drops a registered tool from `tools/list`, so work outward:

* **Did the server start at all?** `@mcp.tool` without parentheses raises at import time, and a crashed server looks a lot like an empty one in some hosts. Run `python server.py` yourself.
* **Is the tool on the `mcp` the host is running?** A second `MCPServer(...)` in another module is a different, empty server. Check which object the host's command actually imports.
* **Did two tools share a name?** Then one of them is gone. Look for `Tool already exists:` in the server log.
* **Is the host's list stale?** Adding a tool after startup only reaches clients that handle `notifications/tools/list_changed`. Restarting the host is the blunt fix.
* **Did something write to `stdout`?** On a stdio transport, stdout *is* the protocol: one stray `print()` and the host drops the connection, which some hosts render as a server with nothing in it. Log with the `logging` module instead. The rest of the host-side checklist is on **[Connect to a real host](get-started/real-host.md)**.

An "invalid" tool name is *not* on that list: a non-conforming name logs a warning but the tool is registered and listed anyway.

## `MCPError: Server returned an error response`

The server refused the HTTP request outright, with a body that is not JSON-RPC, so the python `Client` has nothing better to show you than this stand-in.

By far the most common cause is a freshly deployed Streamable HTTP server. `streamable_http_app()` (and `mcp.run("streamable-http")`) with no `transport_security=` defaults to **DNS-rebinding protection**: it accepts only requests whose `Host` header is localhost. That is the right default on your laptop and the wrong one behind a real hostname:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Deploy that, point a client at it, and the connection fails on the handshake:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

The words the server actually sent, `421` and `Invalid Host header`, never reach you: the 421 body has no `Content-Type: application/json`, so the client cannot parse it. They are in the **server's log**, which is where to look next:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

The fix is `transport_security=`. Allowlist the hostname you actually serve:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    That is the whole change. The identical client now connects, negotiates `2026-07-28`, and
    calls `forecast`.

**[Deploy & scale](run/deploy.md)** covers what each field means, the reverse-proxy case, and everything else that changes at deploy time. And `421 Misdirected Request` / `Invalid Host header`, right below, is the same failure seen from the other side.

## `421 Misdirected Request` / `Invalid Host header`

This is `Server returned an error response`, seen from anything that is *not* the python `Client`: curl, a browser's network tab, a reverse proxy's access log, or another SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` is HTTP's own reason phrase for the status; `Invalid Host header` is the SDK's response body; and the python `Client` renders the same event as `Server returned an error response`. All three are one refusal. The check runs against the **`Host` header the request carries**, not the address the server bound, so a reverse proxy that forwards the public hostname trips it exactly as a direct client does.

The fix is the same `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` shown under `Server returned an error response`. Two of its edges are worth naming:

* An `allowed_hosts` entry is an exact string. `"mcp.example.com"` matches a bare `Host` header and `"mcp.example.com:*"` matches any explicit port. List both.
* A `403` with the body `Invalid Origin header` is the sibling check on the `Origin` header. It only fires for browsers (nothing else sends `Origin`), and `allowed_origins=` is its allowlist.

**[Deploy & scale](run/deploy.md)** has the full treatment, including when switching the check off is the honest configuration.

## `RuntimeError: Task group is not initialized. Make sure to use run().`

Your MCP app is mounted inside another ASGI app, and nothing started its **session manager**.

`mcp.streamable_http_app()` returns a Starlette app whose own lifespan starts the manager, and `uvicorn server:app` runs that lifespan for you. But Starlette **never runs a mounted sub-application's lifespan**, so the moment the app goes inside a `Mount`, the manager never starts and the first request explodes:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

The server starts. The route resolves. Then `uvicorn` prints this for every request:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

The client sees a 500. The fix is a lifespan on the **host** app that enters `mcp.session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

**[Add to an existing app](run/asgi.md)** is the page for this, including several servers in one app and FastAPI. Two neighbouring strings from the same class:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` The manager is single-use; entering the same app's lifespan twice hits it.
* `mcp.session_manager` only exists **after** `streamable_http_app()` has been called, so build the routes first and touch the manager only inside the lifespan.

## `MCPError: Session not found`

The server does not recognise the `Mcp-Session-Id` your client sent, almost always because the server **restarted** (or you were routed to a different instance). Sessions live in that one process's memory.

There is no server bug to find. The HTTP response is a `404` whose body *is* JSON-RPC, so, unlike the `421` above, the python `Client` shows you this one verbatim:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

The fix is to reconnect: leave the `async with Client(...)` block and enter a new one, which negotiates a fresh session. For a long-lived client, that means catching `MCPError` around your calls and reconnecting on this message rather than retrying inside a dead session.

If it happens *without* a restart, you are running more than one worker without sticky sessions: each worker holds its own session table, so a request routed to the wrong one lands here. **[Deploy & scale](run/deploy.md)** and **[Serving legacy clients](run/legacy-clients.md)** own that story and its two fixes (sticky routing, or `stateless_http=True`).

For the server operator, the matching log line is `Rejected request with unknown or expired session ID: <id>`. It is logged at `INFO`, so it is invisible at the usual `WARNING` threshold. Seeing it in bursts right after a deploy is normal; every connected client is reconnecting.

## `MCPError: Method not found`

One side sent a JSON-RPC request the other has no handler for, and `e.error.data` names the method. The usual cause is an **era mismatch**: a method that exists in one protocol revision and not in the other, sent to a peer on the wrong one, such as a `2025`-era `resources/subscribe` arriving at a `2026-07-28` connection, or a `2026`-only `subscriptions/listen` sent by a client pinned to `mode="legacy"`. **[Protocol versions](protocol-versions.md)** is the map of which side speaks what, and the other honest cause (an optional capability you never registered a handler for) is on **[Completions](servers/completions.md)**.

One thing does **not** produce this error, despite being a request the modern protocol removed: a tool calling `ctx.elicit()` on a `2026-07-28` connection. The server refuses to *send* that request at all, so what you get instead is `Cannot send 'elicitation/create': ...`, further down this page.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'`

Your server wants to ask the user something, and this client never said it can be asked.

An elicitation resolver refuses up front when the connected client did not declare form elicitation, and `e.error.data` names exactly what is missing:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Pass `elicitation_callback=` to `Client(...)`. Registering the callback *is* the capability declaration; there is no second switch:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[Client callbacks](client/callbacks.md)** lists the others (`sampling_callback`, `list_roots_callback`), each of which is a declaration in the same way.

!!! info
    `-32021` is `MISSING_REQUIRED_CLIENT_CAPABILITY`, one of three error codes the 2026-07-28
    spec adds. None of them is an exception class: they all arrive as `MCPError`, and
    `e.error.code` is where to look. `mcp_types` exports the constants. The other two are
    `-32020` `HEADER_MISMATCH` (an HTTP header disagrees with the request body it accompanies)
    and `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (the request named a version this server does not
    speak). A conforming SDK client cannot produce either, so if you see one, look at whatever is
    rewriting requests between your client and your server.

## `MCPError: Elicitation not supported`

The same gap as `Client did not declare the form elicitation capability ...`, spelled by the paths that don't check up front: the server needed an elicitation answered, and the connected client registered no `elicitation_callback`.

You see this one from `ctx.elicit()` on a legacy connection, and on any connection at all from a returned multi-round-trip question (**[Multi-round-trip requests](handlers/multi-round-trip.md)**) that reaches a client with no callback to answer it. The fix is identical: pass `elicitation_callback=` to `Client(...)`. There is no version of "the user wasn't asked" that your tool receives as a `decline`; a client that cannot be asked is a failed call, so design your tools for it.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.`

Your handler tried to reach the client mid-request, on a connection where nothing can carry a request from the server. There are exactly two ways to be on one.

**A `2026-07-28` connection: any transport, always.** The modern protocol has no server-initiated requests at all, so the server refuses before anything is sent. `ctx.elicit()` inside a tool is the classic way to meet this (on the very first in-memory test, since `Client(server)` negotiates `2026-07-28` without being asked), and passing `elicitation_callback=` changes nothing, because no request ever reaches the client for it to answer:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**A legacy connection on a `stateless_http=True` server.** Statelessness means every request is its own world: no session, no server-to-client stream, and so nowhere to send an `elicitation/create` (or `sampling/createMessage`, or `roots/list`) even for the era that has them:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

The message names the method it could not send. `NoBackChannelError` is the class the server raises, but the wire carries only the base `MCPError`, so the sentence above is your traceback's last line, not the class name.

The fix is the same for both: don't reach back mid-call. Move the question into a **resolver** (or return an `InputRequiredResult` yourself) and it becomes part of the *response*, which every connection can carry:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Same question, same `elicitation_callback` on the client. The difference is under the hood: a resolver lets the server *return* the question from the call instead of pushing it, so nothing ever flows server-to-client. **[Elicitation](handlers/elicitation.md)** covers resolvers; **[Multi-round-trip requests](handlers/multi-round-trip.md)** covers what happens on the wire.

!!! check
    The tool with `ctx.elicit()` is not wrong, it is *pre-2026*. Connect with `mode="legacy"`
    (the classic `initialize` handshake, spec `2025-11-25` and earlier) to a server that is not
    `stateless_http=True`, and it works, because the server-to-client channel exists there.
    **[Protocol versions](protocol-versions.md)** is the page on what each version has.

## `MCPError: Invalid or expired requestState`

The server could not verify the `requestState` token your client echoed back, so it refused the round.

`requestState` is the opaque resume token a **[multi-round-trip](handlers/multi-round-trip.md)** call carries between legs. `MCPServer` seals it on the way out and verifies every echo, and it verifies *every* inbound `request_state` on `tools/call`, `prompts/get`, and `resources/read`, even for a handler that never mints one. So a token this process didn't seal is refused wherever it lands:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

The message is deliberately frozen: the wire never reveals which check failed. The reason goes to the **server log**, and reading it is the whole diagnosis:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

The reasons you will actually see:

* **`unknown key`** is the one that matters. The default sealing key is generated at process start, so a retry that lands on a **different worker**, a different instance behind a load balancer, or the same server **after a restart** was sealed under a key this process never had. That is not an attacker; it is the default meeting more than one process.
* **`audience`**: the token was sealed by an instance with a *different server name*. The name is the seal's default audience claim, so a fleet must share the name (or set an explicit `RequestStateSecurity(audience=...)`) as well as the keys.
* **`expired`**: the round took longer than the seal's `ttl`, which is 600 seconds and per round, not per call.
* **`malformed`** / **`codec error`**: the token was altered in transit, or was never a sealed token at all.
* **`request binding`**: the token came back with a different tool, different arguments, or a different method.

The multi-process fix is one argument (the *same* `keys` on every instance) plus one thing that is not an argument at all: the same server *name* (or an explicit shared `audience=`).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` seals; every key in the list verifies, which is what makes zero-downtime rotation possible. **[Multi-round-trip requests](handlers/multi-round-trip.md#protecting-requeststate)** explains what the seal protects and the rotation sequence, and **[Deploy & scale](run/deploy.md)** walks the whole two-worker failure and its two-part fix.

!!! tip
    `keys=[...]` refuses a weak key immediately, with an unusually helpful message:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Do what it says.

## Still stuck?

* If a message the SDK produced is not on this page, that is a documentation bug worth reporting on its own.
* Search the [issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues); most error strings appearing there are already someone's write-up.
* Found nothing? [Open an issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) with the full traceback, or ask in [#python-sdk-dev on the MCP Contributors Discord](https://discord.gg/6CSzBmMkjX).

## Recap

* `ExceptionGroup: unhandled errors in a TaskGroup` is never the error. Read the **last line**; catching `MCPError` *inside* the `async with Client(...)` block skips the wrapping entirely.
* `call_tool` does not raise for a failing tool. `Error executing tool ...` and `Unknown tool: ...` are results: check `result.is_error`.
* `Client must be used within an async context manager` -> use `async with`. `Use @tool() instead of @tool` -> add the parentheses.
* `Tool already exists:` in the server log is the only sign that two same-named tools collapsed into one.
* One 421, three spellings: `Server returned an error response` (the python `Client`), `421 Misdirected Request` / `Invalid Host header` (everything else), `Invalid Host header: <host>` (the server log). Fix: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> a mounted app whose host lifespan never entered `mcp.session_manager.run()`.
* `Session not found` -> the server restarted; reconnect.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` needs a server-to-client channel: a `2026-07-28` connection never has one, and `stateless_http=True` takes away the legacy one. Use a resolver. Its neighbour `Method not found` is a request for a method the other side's protocol revision doesn't have.
* `Client did not declare the form elicitation capability ...` and `Elicitation not supported` -> the client is missing `elicitation_callback=`.
* `Invalid or expired requestState` never says why on the wire. The server log does; `unknown key` means share `RequestStateSecurity(keys=[...])` across workers.
