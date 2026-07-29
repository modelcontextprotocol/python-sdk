# Imports & startup time

`import mcp` is close to free, and every entry point loads only what it uses. You get that
without doing anything; this page is for when you want to know *what* loads *when*, or when you
want to move the deferred work to a moment of your choosing.

## What loads when

The `mcp` package is a lazy namespace: `import mcp` binds no protocol types, no pydantic, and
none of the client or server modules. Each name resolves from its home module the first time you
touch it (`from mcp import Client` imports the client, `mcp.Tool` imports the types), and is then
an ordinary attribute. `from mcp import *`, `dir(mcp)` and object identity are unchanged; the
supported way to reach a submodule is still to import it (`import mcp.client.stdio`).

From there, each stack loads with the feature that needs it:

| Loaded on first use of | What loads |
| --- | --- |
| a URL `Client(...)` (or the SSE / streamable-HTTP client modules) | the HTTP client stack (`httpx2`) |
| `streamable_http_app()` / `sse_app()` / `custom_route()` | the web stack (`starlette`, `sse_starlette`, `uvicorn`) |
| the first message parsed for a protocol version | that version's wire-schema package (`mcp_types._v2025_11_25` / `_v2026_07_28`) |
| the first construction or validation of a model | that model's pydantic validator (`defer_build=True`) |
| the first span | the OpenTelemetry API |

None of these is per request. Each is a one-time cost paid where the work happens, and the
steady state afterwards is identical to having loaded it up front. Client code never loads the
server stack, and a stdio server never loads the web stack.

## Prewarming

If you would rather pay the deferred work at startup than on the first request — a
latency-sensitive host, say — trigger it explicitly before you start serving:

```python
--8<-- "docs_src/import_cost/tutorial001.py"
```

Reading a row of a surface map imports that protocol version's wire package, and
`model_rebuild()` builds a model's validator; both are no-ops on anything already built. An HTTP
server needs nothing extra for its transport: building the app (`streamable_http_app()`) at startup
is exactly the moment its web stack loads anyway.
