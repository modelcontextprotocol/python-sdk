# tools

**Start here.** Register tools with `@mcp.tool()`; the SDK infers the JSON
input schema from type hints, the output schema from the return annotation, and
returns `structuredContent` alongside text. `ToolAnnotations` carries
behavioural hints (`readOnlyHint`, `idempotentHint`) the host can show to
users. The client lists tools, inspects schemas + annotations, calls both, and
asserts structured output.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.tools.client

# against a running HTTP server
uv run python -m stories.tools.server --http --port 8000 &
uv run python -m stories.tools.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- `server.py` `calc` — `Literal[...]` and `BaseModel` in the signature become
  the tool's `inputSchema` / `outputSchema` with zero hand-written JSON.
- `server.py` `echo` — `structured_output=False` opts out of schema inference
  for a plain text-only tool.
- `server_lowlevel.py` — the same wire contract built by hand: this is what
  `MCPServer` generates for you.

## Spec

[Tools — server features](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

## See also

`schema_validators/` (every input-schema source: pydantic / TypedDict /
dataclass / dict), `error_handling/` (`is_error` vs protocol error),
`streaming/` (progress mid-call).
