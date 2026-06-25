# stickynotes

The "real app" capstone: tools mutate a sticky-notes board held in the
server's lifespan context, each note is a `note:///{id}` resource,
`notifications/resources/list_changed` fires on add/remove, and `remove_all`
blocks on a form-mode elicitation so the user must explicitly confirm a
destructive clear.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.stickynotes.client

# against a running HTTP server
uv run python -m stories.stickynotes.server --http --port 8000 &
uv run python -m stories.stickynotes.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- **`client.py` `main` → `Client(target, mode=mode, elicitation_callback=...,
  message_handler=...)`** — the construction is the example: callbacks are
  plain constructor kwargs, and `mode=` is explicit. The scripted elicitation
  answer and the `list_changed` event are locals of `main`, so every
  connection starts clean.
- **`server.py` `lifespan` → `Board`** — long-lived mutable state belongs in
  the lifespan context, never a module global. Tools reach it via
  `ctx.request_context.lifespan_context`; this 2-hop path is interim and will
  shorten to `ctx.state.*` in a later release.
- **`add_note` / `remove_note`** — `mcp.add_resource(FunctionResource(...))`
  registers a concrete resource at runtime; `ctx.session.send_resource_list_changed()`
  tells connected clients to re-list. **Gap:** `MCPServer` has no public
  `remove_resource()` yet, so `remove_note` reaches a private attribute — do
  not copy that line. `server_lowlevel.py` shows the clean equivalent:
  `on_list_resources` reads the board and builds the list fresh per call, so
  removal is just `board.notes.pop(...)` with no registry mutation.
- **`remove_all` → `ctx.elicit(...)`** — push-style server→client elicitation
  needs a back-channel and an advertised client capability, so it only runs on
  the legacy-era legs. On a modern connection there is no server→client
  request channel; the modern equivalent is the multi-round-trip
  `InputRequiredResult` flow (see `mrtr/`, not yet implemented). The client
  branches on `client.protocol_version`.

## Caveats

- `list_changed` and `ctx.elicit()` are skipped on modern legs: the
  notification needs a standalone stream and `ctx.elicit()` would raise
  `NoBackChannelError`. `main` branches on
  `client.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS`.

## Spec

- [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [Resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
- [Elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)

## See also

`tools/`, `resources/`, `legacy_elicitation/`, `lifespan/`, `standalone_get/`
(`list_changed` over the GET stream).
