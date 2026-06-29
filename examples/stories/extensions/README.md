# extensions

Writing your own extension (SEP-2133): one identifier bundles a settings entry
under `ServerCapabilities.extensions`, a contributed tool, and a vendor request
method gated on the client declaring the extension back.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.extensions.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.extensions.client --http
```

## What to look at

- `server.py` `class Catalog(Extension)` — the whole extension: `settings()`
  becomes the advertised capability entry, `tools()` contributes a regular tool,
  `methods()` registers a vendor verb. The extension never holds the server; it
  declares contributions and `MCPServer(extensions=[...])` consumes them.
- `server.py` `require_client_extension(ctx, EXTENSION_ID)` — the vendor method
  rejects clients that did not declare the extension with `-32021` (missing
  required client capability) and a machine-readable `requiredCapabilities`
  payload.
- `client.py` `Client(target, extensions={EXTENSION_ID: {}})` — the client-side
  half of the negotiation; on 2026-07-28 it travels in the per-request `_meta`
  envelope.
- `client.py` `client.session.send_request(...)` — vendor methods have no
  `Client`-level helper; the session escape hatch sends them.

## Spec

[SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)
· [Capabilities — `_meta` key grammar](https://modelcontextprotocol.io/specification/draft/basic/index)

## See also

`apps/` (the built-in MCP Apps extension) · `custom_methods/` (the same verb
registered on the lowlevel `Server` by hand, without an extension).
