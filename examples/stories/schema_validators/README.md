# schema-validators

Five ways to type a tool parameter so `MCPServer` derives the JSON-Schema
`inputSchema` and validates arguments before your handler runs: a pydantic
`BaseModel`, a `TypedDict`, a `@dataclass`, a bare `dict[str, Any]`, and a
pydantic model built at runtime with `create_model`. The client lists the
tools, resolves each `who` schema, and round-trips a call.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.schema_validators.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.schema_validators.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.schema_validators.client --http --server server_lowlevel
```

## What to look at

- `client.py` `main` — the body opens with `async with Client(target, mode=mode)
  as client:`. `target` is anything `Client` accepts (an in-process server, a
  transport, or an HTTP URL); the entry point picks it, the story constructs it.
- `server.py` — `who.name` vs `who["name"]`: pydantic and dataclass parameters
  arrive as **instances** (attribute access); TypedDict and `dict[str, Any]`
  arrive as plain dicts.
- `server.py` `greet_dynamic` — the parameter type is not written in the source
  at all: `create_model` builds it at runtime from a JSON Schema dict (the shape
  you'd get from OpenAPI, a config file, or a DB row), then hands it to
  `@mcp.tool()` like any `BaseModel`; the published schema is identical to the
  `greet_pydantic` variant. A `create_model` result is opaque to static type
  checkers, so a `TYPE_CHECKING` branch aliases it to a declared model of the
  same shape — the runtime still uses the dynamic class.
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
