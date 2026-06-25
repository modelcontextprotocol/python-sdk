# roots

> **Deprecated** in the 2026-07-28 protocol (SEP-2577); functional through the
> deprecation window. Migration: accept directory paths as ordinary tool
> parameters or resource URIs instead of relying on `roots/list`.
> TODO(maxisbey): revisit before beta.

The client passes a `list_roots_callback` returning the filesystem locations it
is willing to expose; a server tool calls `ctx.session.list_roots()` mid-request
and the client's callback answers it. Passing the callback is what makes the
client advertise the `roots` capability — there is no separate flag.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.roots.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.roots.client --http --legacy
# same, against the lowlevel-API server variant
uv run python -m stories.roots.client --http --legacy --server server_lowlevel
```

## What to look at

- `client.py` `main` — the
  `Client(target, mode=mode, list_roots_callback=list_roots)` construction is
  the whole client-side story: the callback is wired in as a constructor
  argument, and that alone advertises the capability.
- `client.py` `list_roots` — the callback takes a `ClientRequestContext` and
  returns `ListRootsResult`.
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

`legacy_elicitation/`, `sampling/` — sibling server→client requests on the same
MRTR migration path.
