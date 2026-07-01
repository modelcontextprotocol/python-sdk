# todos-server — the reference MCP server, in Python

A small project todo board where **every server-side MCP feature has a real job**: tools that mutate state, resources that expose it, prompts that seed conversations, sampling that borrows the connected host's model, elicitation that asks the user, progress and logs while it works, and per-resource subscriptions that announce every change. It is a faithful port of the TypeScript SDK's [`examples/todos-server`](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/todos-server) — think of it as the "polls app" of MCP servers: small enough to read in one sitting, real enough that nothing in it is contrived.

It serves **both protocol revisions at once** — 2026-07-28 and 2025-11-25 are negotiated per connection, from the same handlers — and **both transports**: stdio and Streamable HTTP.

## Run it

From this directory:

```bash
# stdio — for hosts that spawn their servers as child processes
uv run python -m mcp_todos_server

# Streamable HTTP — for remote-style connections (default port 3000; --port or $PORT to change)
uv run python -m mcp_todos_server --transport streamable-http
```

Over stdio the server speaks on stdin/stdout (its own diagnostics go to stderr). Over HTTP it serves `http://127.0.0.1:3000/mcp`.

There is no era flag: both entries detect each connection's revision during the handshake, so a 2025-era client and a 2026-era client can talk to the same process — simultaneously, over HTTP.

Any `mcpServers`-style host can spawn it too:

```jsonc
{
    "mcpServers": {
        "todos": { "command": "uv", "args": ["run", "--directory", "/absolute/path/to/examples/servers/todos-server", "python", "-m", "mcp_todos_server"] }
    }
}
```

The TypeScript SDK's reference host, [`cli-client`](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/cli-client), connects to the HTTP entry out of the box:

```bash
uv run python -m mcp_todos_server --transport streamable-http            # terminal A, this repo
pnpm --filter @mcp-examples/cli-client start -- --server http://127.0.0.1:3000/mcp   # terminal B, typescript-sdk repo
```

## What demonstrates what

| Server feature             | Where it lives                                         | Notes                                                                                                                                              |
| -------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tools                      | `add_task`, `add_tasks`, `list_tasks`, `complete_task` | plain CRUD; `add_task` also returns `structuredContent` against an `outputSchema`                                                                 |
| Sampling                   | `prioritize`, `brainstorm_tasks`                       | the server borrows the _host's_ model; the host shows the request for approval first                                                              |
| Elicitation (form)         | `clear_done`, `brainstorm_tasks`                       | schema-driven forms; accept / decline / cancel all handled                                                                                        |
| Multi-round input_required | `brainstorm_tasks`                                     | theme+count form → optional custom-amount round → sampling round; state rides `request_state` as a step-discriminated JSON object, sealed by the SDK |
| Progress                   | `work_through_tasks`, `add_tasks`                      | paced per-task progress notifications via `ctx.report_progress`                                                                                   |
| Logging                    | every mutating tool, via `log_info`                    | honours `logging/setLevel` on 2025 connections and the per-request log-level `_meta` opt-in on 2026-07-28                                         |
| Resources                  | `todos://board`, `todos://tasks/{id}`                  | one concrete resource + a URI template; every task also appears in `resources/list`                                                               |
| Subscriptions              | the board                                              | `resources/subscribe`/`unsubscribe` handlers for 2025-era clients; `subscriptions/listen` streams (over HTTP) for 2026-07-28; every mutation notifies |
| list_changed               | every mutation                                         | resource list + resource updated notifications on both eras                                                                                       |
| Prompts + completions      | `plan-my-day`, `seed-board`                            | argument completion (project names, themes, task ids) wired to `completion/complete` via `@mcp.completion()`                                      |

The two protocol eras differ in how interactive conversations travel: on 2025-era connections the wire carries _pushed_ `elicitation/create` / `sampling/createMessage` requests; on 2026-07-28 the server returns `input_required` results and the client retries the call with the answers. The interactive tools (`brainstorm_tasks`, `clear_done`, `prioritize`) are written **once**, as state machines over `input_required` rounds — on 2025-era connections the example's small `run_interactive` driver fulfils the same rounds as real push-style requests (the job the TypeScript SDK's built-in legacy shim does), so there is no era branch in any handler. For single-question preconditions, the SDK's own era-agnostic form is a `Resolve(...)` dependency that returns `Elicit(...)` — see the [Dependencies tutorial](https://py.sdk.modelcontextprotocol.io/v2/tutorial/dependencies/); this example hand-rolls the rounds instead so the multi-round flow, the sampling rounds, and the carried state are all visible in one place.

## Configuration

| Env var                | Effect                                                                                                                                                       |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `REQUEST_STATE_SECRET` | Key for the sealed `request_state` (≥ 32 bytes). Unset, the SDK generates a per-process key — fine whenever a single process serves the whole flow.        |
| `PORT`                 | HTTP port when `--port` isn't passed (default 3000).                                                                                                        |

## Layout

```text
mcp_todos_server/
    server.py   transport entry: stdio by default, streamable HTTP behind --transport
    todos.py    the application: state, tools, resources, prompts, subscriptions — every feature above
```

## Fidelity to the TypeScript reference

This port is verified against the TypeScript `todos-server` by driving both over stdio and HTTP, on both protocol eras, through an identical scripted scenario (same tool calls, elicitation answers, and sampling replies): every tool result text, structured output, elicitation form, sampling request, progress sequence, and log line matches. Known, deliberate differences:

- **JSON Schema style.** Input schemas come from pydantic here and zod there, so cosmetics differ (pydantic emits `title`s and `$defs` refs for the nested `add_tasks` items). The schemas are semantically identical.
- **`resources/list` composition.** The TypeScript `ResourceTemplate` has a `list` callback; `MCPServer` doesn't, so this example overrides the low-level `resources/list` handler to append one entry per task (the same private-API pattern the everything-server uses for `resources/subscribe` and `logging/setLevel`).
- **`subscriptions/listen` over stdio.** The Python SDK serves 2026-era listen streams on streamable HTTP only; over stdio a listen request is rejected. Board-change notifications over stdio therefore reach 2025-era subscribers only.
- **Legacy HTTP interactivity.** The TypeScript server's per-request HTTP posture refuses push-style sampling/elicitation for 2025-era HTTP clients; the Python server's default Streamable HTTP mode is stateful, so those tools work on that leg here.
- **Legacy HTTP fan-out.** Pre-2026 board-change notifications go to the session that made the mutating call. Over stdio that is every subscriber; with several concurrent 2025-era HTTP sessions, the others don't hear about it (the TypeScript entry broadcasts via its handler notifier). Pre-2026 HTTP handshakes also advertise `listChanged: false` — the SDK exposes no seam to change that on the HTTP path (stdio is patched, see `serve_stdio`).
- **Cancellation granularity.** When a 2025-era client cancels `work_through_tasks`, this SDK interrupts the handler at its next `await` (the in-flight pretend task stays open); the TypeScript server checks between tasks and finishes the in-flight one.
