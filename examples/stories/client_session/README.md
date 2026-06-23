# client-session

`Client` is a thin shell over `ClientSession`. This story shows the
`client.session` escape hatch: the era-specific result slots
(`initialize_result` / `discover_result`), the Optional-vs-narrowed accessors,
and the generic `send_request()` that every typed `client.*()` method wraps.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.client_session.client

# against a running HTTP server
uv run python -m stories.client_session.server --http --port 8000 &
uv run python -m stories.client_session.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- **`client.session`** returns the live `ClientSession`. This is the documented
  escape hatch when `Client` doesn't expose what you need (custom JSON-RPC,
  era-specific result objects, the connect primitives).
- **Exactly one of `initialize_result` / `discover_result`** is ever non-None.
  `Client.__aenter__` ran the connect ladder for you (`mode="legacy"` →
  `initialize()`; `mode="auto"` → `discover()` with fallback; `mode=<version>`
  → `adopt()`); which slot is filled tells you which path it took.
- **`ClientSession.protocol_version` is `str | None`; `Client.protocol_version`
  is `str`.** Same value, different Optional-ness — `Client` guarantees it's
  set inside the `async with` block. Same for `server_info` /
  `server_capabilities`.
- **`send_request(request_model, result_type)`** is the layer beneath
  `client.list_tools()`. See `custom_methods/` for using it to call vendor
  methods `Client` doesn't model.

> When `mode=<version>` is set without `prior_discover=`, the SDK synthesizes
> a placeholder `DiscoverResult` (empty `server_info` / `capabilities`); only
> `protocol_version` is meaningful on that path.

## Building a ClientSession directly

`Client` builds the `ClientSession` for you. To own the connect step yourself
(e.g. to call `discover()` and cache the result, or to drive raw streams from
a custom transport), construct `ClientSession` over a stream pair:

```python
from mcp import ClientSession, StdioServerParameters, stdio_client

async with stdio_client(StdioServerParameters(command="./server")) as (read, write):
    async with ClientSession(read, write) as session:
        result = await session.initialize()      # or: await session.discover()
        tools = await session.list_tools()
```

This is the v1-lineage shape; `Client` exists so you usually don't write it.

## Spec

- [Lifecycle — 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [Lifecycle — 2026-07-28 discover](https://modelcontextprotocol.io/specification/2026-07-28/basic/lifecycle#discover)

## See also

`serve_one/` (server-side mechanics counterpart), `custom_methods/`
(`send_request` for vendor JSON-RPC), `dual_era/` (the connect ladder as the
teaching point).
