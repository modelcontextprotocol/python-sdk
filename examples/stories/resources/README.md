# resources

Expose data by URI: a static resource (`config://app`) and an RFC-6570
template (`greeting://{name}`). One `@mcp.resource()` decorator handles both —
the SDK infers static-vs-template from whether the URI contains `{...}`. The
client lists resources, lists templates, then reads each.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.resources.client

# against a running HTTP server
uv run python -m stories.resources.server --http --port 8000 &
uv run python -m stories.resources.client --http http://127.0.0.1:8000/mcp

# swap in the lowlevel server
uv run python -m stories.resources.client --server server_lowlevel
```

## What to look at

- `server.py` `app_config` vs `greeting` — a URI with no `{}` registers a
  static resource (appears in `resources/list`); a URI with `{name}` registers
  a template (appears only in `resources/templates/list`) and the placeholder
  must match the function parameter name.
- `server_lowlevel.py` `read_resource` — without `MCPServer` you own the URI
  dispatch yourself, including raising `MCPError(code=INVALID_PARAMS, ...)` for
  unknown URIs (matches what `MCPServer` sends).
- `client.py` `isinstance(entry, TextResourceContents)` — `contents` is a list
  of `TextResourceContents | BlobResourceContents`; narrow before reading
  `.text`.

## Not shown here

Subscriptions. Per-URI `resources/subscribe` is a 2025-era RPC being replaced
by `subscriptions/listen` in 2026-07-28; neither is shown in this story. See
`stickynotes/` for `list_changed` notifications.

## Spec

[Resources — server features](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)

## See also

`stickynotes/` (list-changed notifications), `pagination/` (cursor over a long
resource list).
