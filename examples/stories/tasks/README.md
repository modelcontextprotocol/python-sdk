# tasks

Task-augmented execution (SEP-2663). A client declares the
`io.modelcontextprotocol/tasks` extension; the server may then answer a
`tools/call` with a `CreateTaskResult` (carrying a task id) instead of the
`CallToolResult`. `Client.call_tool` drives the polling transparently and
surfaces only the final result — the SEP's recommended client shape.

## Run it

```bash
# stdio (default) — stdio negotiates the modern wire too, so both legs run the
# full flow: the server defers the call as a task, Client.call_tool polls it
# to completion, and a manual leg shows the raw CreateTaskResult -> tasks/get
# wire flow
uv run python -m stories.tasks.client

# HTTP — the same flow over streamable HTTP
uv run python -m stories.tasks.client --http
```

## What to look at

- `server.py` `MCPServer("tasks-example", extensions=[Tasks(default_ttl_ms=...)])` —
  opt in at construction. The extension advertises `io.modelcontextprotocol/tasks`
  and serves `tasks/get`, `tasks/update`, and `tasks/cancel` on the modern wire
  (legacy calls are `METHOD_NOT_FOUND`; the extension is not defined there).
- `mcp.server.tasks.Tasks.intercept_tool_call` — the server DECIDES augmentation;
  the legacy `params.task` field is ignored. It augments only for a client that
  declared the extension on the request, returning a flat `CreateTaskResult`
  (`resultType: "task"`).
- `client.py` `Client(target, extensions=[TasksExtension()])` — the client half
  is a `ClientExtension` whose result claim admits the `CreateTaskResult` and
  lets the server defer. The transparent path is then just
  `await client.call_tool(...)`: the claim's resolver polls `tasks/get`
  (honoring `pollIntervalMs`) and returns the final `CallToolResult`; a
  `failed` task raises `TaskFailedError`. On a legacy connection the
  capability cannot be negotiated, the server must not augment, and the same
  call returns the plain `CallToolResult` — the story guards its manual leg
  on the negotiated capability.
- The manual leg — `session.call_tool(..., allow_claimed=True)` returns the
  typed `CreateTaskResult` (mirroring `allow_input_required`), and the shared
  `mcp.shared.tasks` wrappers (`GetTaskRequest`/`GetTaskResult`) drive `tasks/get`
  by hand over `session.send_request`.

## Scope

This is the core SEP-2663 surface. The tool runs to completion inline, so a task
is recorded directly as `completed` (the SEP allows any initial status), and
finished (completed or failed) tasks live in a pluggable `TaskStore`
(`Tasks(store=...)`, in-memory default) that enforces `default_ttl_ms`. Deferred
to follow-ups, each needing deeper SDK plumbing: background execution (returning
`working` tasks), the in-task `input_required`/`inputResponses` loop over
`tasks/update`, and `notifications/tasks` (the SEP-2243 `Mcp-Name` routing
header is already handled by the shared header table).

## Spec

[SEP-2663 — Tasks extension](https://modelcontextprotocol.io/seps/2663-tasks-extension.md)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)

## See also

`apps/` (the additive half of the extension API),
`custom_methods/` (a non-spec method without an extension).
