# tasks

Task-augmented tool execution. A client sends `tools/call` with a `task` field;
the server records the call under a task id and the client polls `tasks/get` /
`tasks/result`. This is the *interceptive* half of the extension API — the
`Tasks` extension (`io.modelcontextprotocol/tasks`) wraps `tools/call` rather
than only adding tools.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.tasks.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.tasks.client --http
```

## What to look at

- `server.py` `MCPServer("tasks-example", extensions=[Tasks()])` — opt in at
  construction. The extension advertises `io.modelcontextprotocol/tasks` and
  serves `tasks/get`, `tasks/result`, `tasks/cancel`, and `tasks/list`. The
  `render_report` tool is the kind of slower, multi-step work a caller would
  rather run as a task than block on.
- `mcp.server.tasks.Tasks.intercept_tool_call` — the interceptive seam: a plain
  call passes through; a call with a `task` field is recorded and returned with
  the task id in `_meta["io.modelcontextprotocol/related-task"]`.
- `client.py` `main` — start the call as a task, read its `tasks/get` status,
  then fetch the payload with `tasks/result`. The `task` field and `tasks/*`
  methods are outside the spec verbs `Client` exposes, so the thin
  `_start_task` / `_get_task` / `_task_result` helpers wrap `client.session`.

## Caveats

This is a reference implementation for the extension API, not a production task
runtime. A plain `tools/call` (no `task` field) is unchanged — only a call the
client explicitly augments with a `task` field becomes a task. Three deliberate
simplifications:

- The tool runs to completion inline, so a task is observed as `completed`
  immediately (no detached/background execution, no TTL eviction).
- The augmented call returns a normal `CallToolResult` with the task id in
  `_meta` rather than the spec's `CreateTaskResult` — the `tools/call` result
  schema admits only `CallToolResult | InputRequiredResult` (see `TODO(L56)` in
  `mcp.server.runner`), so returning `CreateTaskResult` would require extending
  the methods-layer validation maps. The lifecycle runs through the dedicated
  `tasks/*` methods instead.
- Any tool may be task-augmented on request; per-tool gating on the declared
  `ToolExecution.task_support` (`forbidden`/`optional`/`required`) is not enforced.

## Spec

[Tasks — extensions](https://modelcontextprotocol.io/specification/draft/extensions)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)

## See also

`apps/` (the additive half of the extension API),
`custom_methods/` (a non-spec method without an extension),
`middleware/` (the low-level `tools/call` wrapping the interceptor builds on).
