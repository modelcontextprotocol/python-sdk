# sampling

> **Deprecated** in the 2026-07-28 protocol (SEP-2577); functional through the
> deprecation window. Migration: call your LLM provider directly from the
> server instead of requesting completions through the client.
> TODO(maxisbey): revisit before beta.

A tool that asks the **client's** LLM for a completion mid-call — the inverted
MCP direction. The server holds no model API key; it awaits
`ctx.session.create_message(...)` and the client's `sampling_callback` answers.
Registering the callback is what makes the client advertise the `sampling`
capability — there is no separate flag.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.sampling.client

# against a running HTTP server
uv run python -m stories.sampling.server --http --port 8000 &
uv run python -m stories.sampling.client --http http://127.0.0.1:8000/mcp --legacy
```

## What to look at

- `client.py` `main` — `async with Client(target, mode=mode,
  sampling_callback=on_sample) as client:`. The callback is an ordinary
  constructor kwarg; registering it is the whole opt-in.
- `client.py` `on_sample` — takes `(ClientRequestContext,
  CreateMessageRequestParams)` and returns a `CreateMessageResult`. A real
  host calls its LLM provider here; the example returns a canned answer so the
  round-trip is assertable.
- `server.py` — `await ctx.session.create_message(...)` inside the tool body: a
  server→client request that blocks until the callback answers. There is no
  `Context.sample()` sugar; reaching `ctx.session` is the public path.
- `server_lowlevel.py` — the same call from `ServerRequestContext.session`,
  with the `CallToolResult` built by hand.

## Caveats

- **Legacy-era only.** `sampling/createMessage` is a server-initiated request
  with no 2026-07-28 wire carrier until the multi-round-trip runtime lands
  ([#2898](https://github.com/modelcontextprotocol/python-sdk/issues/2898)), so
  this story runs with `era = "legacy"` and the harness pins the handshake path.
- `ctx.session.create_message()` is `@deprecated`; the
  `# pyright: ignore[reportDeprecated]` is deliberate. There is no
  non-deprecated server-side path until the multi-round-trip runtime lands.
- `ctx.session.*` is the interim 2-hop path; a later release will shorten it.
- `Client` has no `sampling_capabilities=` kwarg, so the `sampling.tools`
  sub-capability (tools-in-sampling) is unreachable from the high-level client.
  Drop to `ClientSession` if you need it.

## Spec

[Sampling — client features](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)

## See also

`legacy_elicitation/`, `roots/` — sibling server→client requests on the same
MRTR migration path.
