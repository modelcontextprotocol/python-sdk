# Story examples

One feature per folder. Each story is a small, self-verifying program: a
`server.py` (plus, where the wire contract is worth seeing by hand, a
`server_lowlevel.py`) and a `client.py` whose `scenario(client)` makes
assertions and exits non-zero on failure. The code you read here is the same
code CI runs — there is no separate test double.

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

[`manifest.toml`](manifest.toml) declares each story's transports, era, and
variants; `tests/examples/` expands it.

## Layout

`_harness.py` and `_hosting.py` are scaffolding that adapts a story's
`build_server()` / `build_app()` to argv (stdio vs `--http`) and to the
in-process test bridge. They isolate the parts of the SDK's hosting surface
that are still moving — **don't copy them into your own project**; copy the
`server.py` / `client.py` bodies instead. `_shared/` holds an in-process OAuth
authorization server reused by the auth stories.

## Stories

| story | what it shows | status |
|---|---|---|
| **— start here —** | | |
| [`tools`](tools/) | `@mcp.tool()`, schema inference, structured output, annotations | ready |
| [`prompts`](prompts/) | `@mcp.prompt()`, list/get, argument completion | ready |
| [`resources`](resources/) | `@mcp.resource()`, list/read, URI templates | ready |
| [`lifespan`](lifespan/) | startup/shutdown lifespan, per-request state injection | ready |
| [`dual_era`](dual_era/) | one server factory serving both protocol eras; era-neutral accessors | ready |
| [`custom_version`](custom_version/) | restricting `supported_protocol_versions` | ready |
| **— feature stories —** | | |
| [`streaming`](streaming/) | progress notifications, in-flight logging, cancellation | ready |
| [`elicitation`](elicitation/) | server pauses a tool to ask the user (form + url) | ready (legacy-era) |
| [`sampling`](sampling/) | server asks the client's LLM mid-tool (push request) | ready (legacy-era) |
| [`stickynotes`](stickynotes/) | capstone: tools mutate state → resources + `list_changed` + elicit guard | ready |
| [`custom_methods`](custom_methods/) | vendor-prefixed JSON-RPC via `add_request_handler` / `send_request` | ready |
| [`schema_validators`](schema_validators/) | tool input schema from pydantic / TypedDict / dataclass / dict | ready |
| [`middleware`](middleware/) | server-side request/response middleware | ready |
| [`parallel_calls`](parallel_calls/) | N×M concurrent calls; per-call notification attribution | ready |
| [`roots`](roots/) | client-declared roots, server reads them via `ctx` | ready (legacy-era) |
| [`pagination`](pagination/) | manual cursor loop over list endpoints | ready |
| [`error_handling`](error_handling/) | `is_error` results vs `MCPError`; `ToolError` | ready |
| [`client_session`](client_session/) | dropping to `client.session` / `ClientSession` mechanics | ready |
| [`serve_one`](serve_one/) | building a `Connection` by hand and calling `serve_one` directly | ready |
| **— HTTP hosting —** | | |
| [`stateless_legacy`](stateless_legacy/) | `streamable_http_app()` default posture; the one-liner deploy | ready |
| [`json_response`](json_response/) | `json_response=True` mode; raw 2026 POST envelope on the wire | ready |
| [`legacy_routing`](legacy_routing/) | `is_legacy_request()` classifier in front of a sessionful 1.x deploy | ready |
| [`starlette_mount`](starlette_mount/) | mounting `streamable_http_app()` under a Starlette/FastAPI sub-path | ready |
| [`sse_polling`](sse_polling/) | SEP-1699 `closeSSE()` + `Last-Event-ID` resume via `EventStore` | ready |
| [`standalone_get`](standalone_get/) | server-initiated `list_changed` over the sessionful GET stream | ready |
| [`reconnect`](reconnect/) | explicit `discover()`, persist `DiscoverResult`, zero-RTT reconnect | ready |
| [`bearer_auth`](bearer_auth/) | `requireBearerAuth`, PRM metadata, static-token verifier, `ctx.authInfo` | ready |
| [`oauth`](oauth/) | full `authorization_code` grant against an in-process AS | ready |
| [`oauth_client_credentials`](oauth_client_credentials/) | `client_credentials` grant; minimal in-process token endpoint | ready |
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
