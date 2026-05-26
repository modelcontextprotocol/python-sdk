# MCP Server Cards — example implementation

A self-contained, runnable example of what **Server Card** ([SEP-2127][sep])
support could look like in the Python SDK. It mirrors the TypeScript source of
truth in [`experimental-ext-server-card`][ext] and follows the SDK's
`mcp.types` conventions, so the `mcp_server_card/` library could be lifted into
`mcp/experimental/server_card/` largely unchanged.

A Server Card is a static metadata document — typically published at
`https://<host>/.well-known/mcp/server-card` — that describes a remote MCP
server's identity, transport endpoints, and supported protocol versions, so a
client can discover and connect to it *before* initialization.

```
mcp_server_card/
  types.py          # Pydantic models — 1:1 port of schema.ts (camelCase wire format)
  schema.json       # bundled JSON Schema (from experimental-ext-server-card)
  validation.py     # JSON Schema + semantic validation -> typed models
  client.py         # fetch_server_card / load_server_card / well_known_url
  server.py         # build_server_card / write_server_card / mount_server_card / ...
  cli.py            # `mcp-server-card` — validate / fetch / schema
examples/
  serve_card.py     # server: generate, then WRITE a file OR SERVE at .well-known
  consume_card.py   # client: fetch + validate + act on a card
tests/
  test_server_card.py
```

## Design at a glance

**One type port, two consumers.** `types.py` is the only place the schema is
expressed. `Icon` is reused from `mcp.types` (it already exists in the core
spec). The `_meta` and `$schema` fields keep their literal JSON keys via
explicit aliases; everything else is camelCased by the same `to_camel`
generator the rest of the SDK uses.

### Clients: consume + validate

```python
from mcp_server_card import fetch_server_card

# resolves <origin>/.well-known/mcp/server-card, fetches, validates
card = await fetch_server_card("https://dice.example.com")
for remote in card.remotes or []:
    print(remote.type, remote.url, remote.supported_protocol_versions)
```

Validation is two layers, both run by `parse_server_card` / `parse_server`:

1. **JSON Schema** against the bundled `schema.json` (the same artifact the
   experimental repo validates its examples against) — authoritative structure.
2. **Pydantic** field constraints + semantic guards JSON Schema can't express
   (e.g. rejecting version *ranges* like `^1.2.3`).

Failures raise `ServerCardValidationError` carrying every problem at once.

### Servers: generate, then publish

Build the card once from the server's identity, then pick a publishing path:

```python
from mcp_server_card import server_card_from_implementation, streamable_http_remote

card = server_card_from_implementation(
    "io.modelcontextprotocol.examples/dice-roller",   # reverse-DNS card name
    mcp,                                              # an MCPServer (or any Implementation)
    remotes=[streamable_http_remote("https://dice.example.com/mcp")],
)
```

- **Write a static file** (publish to a CDN / `.well-known`):
  `write_server_card(card, "server-card.json")`
- **Serve from a live MCPServer**: `add_server_card_route(mcp, card)` — adds the
  unauthenticated `GET /.well-known/mcp/server-card` route to its Starlette app.
- **Serve from any Starlette app**: `mount_server_card(app, card)`.

## Running

```bash
uv sync

# tests
uv run pytest

# server: write a static card file
uv run python examples/serve_card.py write ./server-card.json

# server: serve it live (Ctrl-C to stop)
uv run python examples/serve_card.py serve --port 8000

# client: fetch + validate it (in another shell)
uv run python examples/consume_card.py http://127.0.0.1:8000

# CLI
uv run mcp-server-card validate ./server-card.json
uv run mcp-server-card fetch http://127.0.0.1:8000
uv run mcp-server-card schema
```

## Notes / open questions

- **Well-known path.** Uses `/.well-known/mcp/server-card` per the experimental
  repo's README. The `schema.ts` doc comment says `mcp-server-card` (no
  subpath) — worth reconciling upstream. The path is a parameter everywhere.
- **`ServerCard` vs `Server`.** `.well-known` serves `ServerCard` (no
  `packages`); the registry `server.json` shape is the `Server` superset, parsed
  with `parse_server`.
- **Media type.** Served as `application/json`; SEP-2127 defines no dedicated
  media type.
- **Schema distribution.** `schema.json` is bundled for offline validation. A
  real SDK integration would track the version published at
  `static.modelcontextprotocol.io` and regenerate it the same way the SDK
  generates its own types.

[sep]: https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2127
[ext]: https://github.com/modelcontextprotocol/experimental-ext-server-card
