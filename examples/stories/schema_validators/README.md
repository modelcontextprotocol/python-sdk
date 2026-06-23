# schema-validators

Four ways to type a tool parameter so `MCPServer` derives the JSON-Schema
`inputSchema` and validates arguments before your handler runs: a pydantic
`BaseModel`, a `TypedDict`, a `@dataclass`, and a bare `dict[str, Any]`. The
client lists the tools, resolves each `who` schema, and round-trips a call.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.schema_validators.client

# against a running HTTP server
uv run python -m stories.schema_validators.server --http --port 8000 &
uv run python -m stories.schema_validators.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- `server.py` — `who.name` vs `who["name"]`: pydantic and dataclass parameters
  arrive as **instances** (attribute access); TypedDict and `dict[str, Any]`
  arrive as plain dicts.
- `client.py` — the listed `inputSchema` for the three typed variants nests a
  `$defs`/`$ref` object with a `name` property; `greet_dict` publishes only
  `{"type": "object", "additionalProperties": true}` — no field validation.
- `server_lowlevel.py` — the same schemas written by hand. There is no
  reflection layer at this tier; you author JSON Schema and unpack
  `params.arguments` yourself.

## Caveats

- Pydantic emits local `#/$defs/` references for nested models. The SDK does
  not dereference network `$ref`s (SEP-2106 MUST NOT); only same-document refs
  are resolved during validation.
- `PersonTD` is `total=True`, so its nested schema requires both `name` and
  `title`; the `BaseModel` and `@dataclass` variants default `title="friend"`,
  so only `name` is required there. Use `typing.NotRequired[...]` to mark
  optional TypedDict fields.

## Spec

[Tools — input schema](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#input-schema)

## See also

`tools/` (output schema → `structuredContent`), `error_handling/` (what
happens when validation fails).
