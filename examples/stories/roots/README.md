# roots

The client registers a `list_roots_callback` returning the filesystem locations
it is willing to expose; a server tool calls `ctx.session.list_roots()`
mid-request and the client's callback answers it. Registering the callback is
what makes the client advertise the `roots` capability — there is no separate
flag.

> **Deprecated.** The roots capability is deprecated as of 2026-07-28
> (SEP-2577). New servers should accept directory paths as ordinary tool
> parameters or resource URIs instead.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.roots.client

# against a running HTTP server
uv run python -m stories.roots.server --http --port 8000 &
uv run python -m stories.roots.client --http http://127.0.0.1:8000/mcp --legacy
```

## What to look at

- `client.py` `list_roots` — the callback takes a `ClientRequestContext` and
  returns `ListRootsResult`; passing it as `list_roots_callback=` is what
  advertises the capability.
- `server.py` — `await ctx.session.list_roots()` inside the tool body: a
  server→client request that blocks until the callback answers.
- `server_lowlevel.py` — the same call from `ServerRequestContext.session`,
  with the `CallToolResult` built by hand.

## Caveats

- **Legacy-era only.** `roots/list` is a server-initiated request with no
  2026-07-28 wire carrier until the multi-round-trip runtime lands
  ([#2898](https://github.com/modelcontextprotocol/python-sdk/issues/2898)), so
  this story runs with `era = "legacy"` and the harness pins the handshake path.
- `ctx.session.list_roots()` is `@deprecated`; the
  `# pyright: ignore[reportDeprecated]` is deliberate. There is no
  non-deprecated server-side path until the multi-round-trip runtime lands.
- `ctx.session.*` is the interim 2-hop path; a later release will shorten it.
- `notifications/roots/list_changed` is intentionally not shown — removed in
  2026-07-28 (SEP-2575) and deprecated on the legacy path.

## Spec

[Roots — client features](https://modelcontextprotocol.io/specification/2025-11-25/client/roots)

## See also

`elicitation/`, `sampling/` — sibling server→client requests on the same MRTR
migration path.
