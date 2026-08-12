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

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.error_handling.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.error_handling.client --http --server server_lowlevel
```

## What to look at

- `client.py` `main` — opens with `async with Client(target, mode=mode) as
  client:`. Inside it, `await` returns for `is_error` results and
  `except MCPError` catches protocol errors; the client never auto-raises on
  `is_error`.
- `server.py` — `raise ToolError(...)` vs `raise MCPError(...)`: same `raise`
  keyword, opposite wire channel. The tool wrapper re-raises `ToolError` and
  `MCPError` through their respective channels; unexpected exceptions are logged
  and sanitized.
- `server_lowlevel.py` — no wrapper: you build `CallToolResult(is_error=True)`
  yourself, and `MCPError` is the only way to pick a JSON-RPC error code.

## Caveats

- This story does not show an unexpected exception. `MCPServer` logs its traceback
  and returns `An unexpected error occurred while executing tool <name>`; use
  `ToolError` when the model needs a safe, specific recovery hint.
- `ToolError` messages are sent to the client verbatim. A lowlevel handler still
  needs to build a `CallToolResult` directly when it wants full control over the
  result shape.

## Spec

[Tools — error handling](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)

## See also

`tools/` (the happy path), `streaming/` (cancellation as a third error-adjacent
surface).
