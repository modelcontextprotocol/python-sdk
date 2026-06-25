# Story examples

One feature per folder. Each story is a small, self-verifying program: a
`server.py` (plus, where the wire contract is worth seeing by hand, a
`server_lowlevel.py`) and a `client.py` whose `main()` makes assertions and
exits non-zero on failure. The code you read here is the same code CI runs —
there is no separate test double.

## How to read a story

Start with the story's README, then `server.py`, then `client.py`. Every
`client.py` exports `async def main(target, *, mode="auto")` — or
`main(targets, ...)` for the stories that open more than one connection — and
constructs the `Client` itself, so the body opens with the one line a client
example exists to teach: `async with Client(target, mode=mode) as client:`.
The `run_client(main)` call in the `__main__` block is only argv plumbing
(stdio vs `--http`, which `mode` to pass); it never hides how the client
connects.

## Running a story

From the repository root:

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.tools.client

# against a running HTTP server
uv run python -m stories.tools.server --http --port 8000 &
uv run python -m stories.tools.client --http http://127.0.0.1:8000/mcp
```

The full matrix (every story × transport × era × server-variant) runs under
pytest:

```bash
uv run --frozen pytest tests/examples/          # everything
uv run --frozen pytest tests/examples/ -k tools # one story
```

[`manifest.toml`](manifest.toml) declares each story's transports, era, status,
and variants; `tests/examples/` expands it.

## Layout

`_hosting.py` adapts a story's `build_server()` / `build_app()` to argv (stdio
vs `--http` serving); `_harness.py` is the client-side mirror — it picks the
`target` that `main()` connects to (a stdio subprocess by default, a URL under
`--http`). They isolate the parts of the SDK's hosting surface
that are still moving — **don't copy them into your own project**; copy the
`server.py` / `client.py` bodies instead. `_shared/` holds an in-process OAuth
authorization server reused by the auth stories.

## Stories

The **status** column is the feature's standing in the protocol, from
[`manifest.toml`](manifest.toml): `current`, `legacy` (a 2025 handshake-era
mechanism with a 2026-era replacement), or `deprecated` (deprecated by
SEP-2577; functional through the deprecation window). Each non-`current` story's README
opens with a banner saying what replaces it.

| story | what it shows | status |
|---|---|---|
| **— start here —** | | |
| [`tools`](tools/) | `@mcp.tool()`, schema inference, structured output, annotations | current |
| [`prompts`](prompts/) | `@mcp.prompt()`, list/get, argument completion | current |
| [`resources`](resources/) | `@mcp.resource()`, list/read, URI templates | current |
| [`lifespan`](lifespan/) | startup/shutdown lifespan, per-request state injection | current |
| [`dual_era`](dual_era/) | one server factory serving both protocol eras; era-neutral accessors | current |
| **— feature stories —** | | |
| [`streaming`](streaming/) | progress notifications, in-flight logging, cancellation | current |
| [`legacy_elicitation`](legacy_elicitation/) | server pauses a tool to ask the user (form + url) via a push request | legacy |
| [`sampling`](sampling/) | server asks the client's LLM mid-tool (push request) | deprecated |
| [`stickynotes`](stickynotes/) | capstone: tools mutate state → resources + `list_changed` + elicit guard | current |
| [`custom_methods`](custom_methods/) | vendor-prefixed JSON-RPC via `add_request_handler` / `send_request` | current |
| [`schema_validators`](schema_validators/) | tool input schema from pydantic / TypedDict / dataclass / dict | current |
| [`middleware`](middleware/) | server-side request/response middleware | current |
| [`parallel_calls`](parallel_calls/) | two clients rendezvous in one tool; per-call progress attribution | current |
| [`roots`](roots/) | client-declared roots, server reads them via `ctx` | deprecated |
| [`pagination`](pagination/) | manual cursor loop over list endpoints | current |
| [`error_handling`](error_handling/) | `is_error` results vs `MCPError`; `ToolError` | current |
| [`serve_one`](serve_one/) | building a `Connection` by hand and calling `serve_one` directly | current |
| **— HTTP hosting —** | | |
| [`stateless_legacy`](stateless_legacy/) | `streamable_http_app()` default posture; the one-liner deploy | current |
| [`json_response`](json_response/) | `json_response=True` mode; raw 2026 POST envelope on the wire | current |
| [`legacy_routing`](legacy_routing/) | `classify_inbound_request()` era routing in front of a sessionful 1.x deploy | current |
| [`starlette_mount`](starlette_mount/) | mounting `streamable_http_app()` under a Starlette/FastAPI sub-path | current |
| [`sse_polling`](sse_polling/) | SEP-1699 `closeSSE()` + `Last-Event-ID` resume via `EventStore` | legacy |
| [`standalone_get`](standalone_get/) | server-initiated `list_changed` over the sessionful GET stream | legacy |
| [`reconnect`](reconnect/) | explicit `discover()`, persist `DiscoverResult`, zero-RTT reconnect | current |
| [`bearer_auth`](bearer_auth/) | `TokenVerifier` + `AuthSettings` bearer gate, PRM metadata, `get_access_token()` | current |
| [`oauth`](oauth/) | full `authorization_code` grant against an in-process AS | current |
| [`oauth_client_credentials`](oauth_client_credentials/) | `client_credentials` grant; minimal in-process token endpoint | current |
| **— deferred (README only) —** | | |
| [`caching`](caching/) | `CacheableResult` ttl/scope hints; client honouring | not yet implemented |
| [`mrtr`](mrtr/) | `InputRequiredResult` round-trip with `requestState` HMAC | not yet implemented — [#2898](https://github.com/modelcontextprotocol/python-sdk/issues/2898) |
| [`subscriptions`](subscriptions/) | `subscriptions/listen`, `ServerEventBus`, `Client.listen()` | not yet implemented — [#2901](https://github.com/modelcontextprotocol/python-sdk/issues/2901) |
| [`tasks`](tasks/) | `io.modelcontextprotocol/tasks` extension | not yet implemented |
| [`apps`](apps/) | MCP Apps: `ui://` resource + `_meta.ui` | not yet implemented — [#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896) |
| [`skills`](skills/) | SEP-2640 skills extension | not yet implemented — [#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896) |
| [`events`](events/) | `io.modelcontextprotocol/events` extension | not yet implemented |

The TypeScript SDK's `repl`, `client-quickstart`, and `server-quickstart`
examples are intentionally not ported (interactive / external network deps);
its `hono` example maps to `starlette_mount/`.
