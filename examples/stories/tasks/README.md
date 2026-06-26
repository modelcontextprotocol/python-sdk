# tasks

Task-augmented execution (SEP-2663). A client declares the
`io.modelcontextprotocol/tasks` extension; the server may then answer a
`tools/call` with a `CreateTaskResult` (carrying a task id) instead of blocking,
and the client polls `tasks/get` for status and the eventual result.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.tasks.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.tasks.client --http
```

## What to look at

- `server.py` `MCPServer("tasks-example", extensions=[Tasks(default_ttl_ms=...)])` —
  opt in at construction. The extension advertises `io.modelcontextprotocol/tasks`
  and serves `tasks/get` and `tasks/cancel`.
- `mcp.server.tasks.Tasks.intercept_tool_call` — the server DECIDES augmentation;
  the legacy `params.task` field is ignored. It augments only for a client that
  declared the extension on the request, returning a flat `CreateTaskResult`
  (`resultType: "task"`).
- `client.py` `Client(target, extensions=[advertise(EXTENSION_ID)])` — declaring the
  extension is what lets the server defer; `main` then reads the `CreateTaskResult`
  and polls `tasks/get`, whose completed `DetailedTask` inlines the original
  `CallToolResult`.

## Scope

This is the SEP-2663 conformant *core*. The tool runs to completion inline (so a
task is observed as `completed` immediately), and the store is in-memory. Deferred
to follow-ups, each needing deeper SDK plumbing: `tasks/update` + the MRTR
`input_required` loop, `ToolExecution.taskSupport` gating with the `-32021`
required-task error, `notifications/tasks`, and SEP-2243 task routing headers.

## Spec

[SEP-2663 — Tasks extension](https://modelcontextprotocol.io/seps/2663-tasks-extension.md)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)

## See also

`apps/` (the additive half of the extension API),
`custom_methods/` (a non-spec method without an extension).
