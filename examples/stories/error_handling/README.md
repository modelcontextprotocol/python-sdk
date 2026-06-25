# error-handling

Tool *execution* failures travel as a successful `CallToolResult` with
`is_error=True` so the LLM can read the message and self-correct.
*Protocol* failures travel as a JSON-RPC error that the client catches as
`MCPError`. This story shows how to produce each from a tool body — `raise
ToolError(...)` vs `raise MCPError(...)` on `MCPServer`; an explicit
`is_error=True` return vs `raise MCPError` on `lowlevel.Server` — and how a
client tells them apart.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.error_handling.client

# against a running HTTP server
uv run python -m stories.error_handling.server --http --port 8000 &
uv run python -m stories.error_handling.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- `client.py` `main` — opens with `async with Client(target, mode=mode) as
  client:`. Inside it, `await` returns for `is_error` results and
  `except MCPError` catches protocol errors; the client never auto-raises on
  `is_error`.
- `server.py` — `raise ToolError(...)` vs `raise MCPError(...)`: same `raise`
  keyword, opposite wire channel. The tool wrapper re-raises `MCPError`
  verbatim and wraps everything else as an `is_error` result.
- `server_lowlevel.py` — no wrapper: you build `CallToolResult(is_error=True)`
  yourself, and `MCPError` is the only way to pick a JSON-RPC error code.

## Caveats

- The "any other exception → `is_error` result" contract on `MCPServer` and the
  "uncaught exception → `code=0`" behaviour on `lowlevel.Server` are **not
  shown** — the contract is under design and the legacy code is a known spec
  divergence. This story will grow those cases once the contract lands.
- `MCPServer` prefixes the execution-error message with
  `"Error executing tool {name}: "`; build a `CallToolResult` directly from a
  lowlevel handler if you need verbatim control.
- `client.py` reads `e.error.data` rather than `e.data`; the convenience
  property carries a `no cover` pragma that `strict-no-cover` would trip.

## Spec

[Tools — error handling](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)

## See also

`tools/` (the happy path), `streaming/` (cancellation as a third error-adjacent
surface).
