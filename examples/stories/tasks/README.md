# tasks

Task-augmented execution (SEP-2663). A client declares the
`io.modelcontextprotocol/tasks` extension; the server may then answer a
`tools/call` with a `CreateTaskResult` (carrying a task id) instead of the
`CallToolResult`, and the client fetches the result via `tasks/get`.

## Run it

```bash
# stdio (default) — stdio negotiates the modern wire too, so the extension is
# carried on both legs: the server defers the call as a task and the client
# reads the result back via tasks/get
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
- `client.py` `Client(target, extensions=[advertise(EXTENSION_ID)])` — declaring the
  extension is what lets the server defer; `main` then reads the `CreateTaskResult`
  and fetches `tasks/get`, whose completed envelope inlines the original
  `CallToolResult`. On a legacy connection the capability cannot be negotiated
  and the same `tools/call` degrades to a plain `CallToolResult`, so the story
  guards its task leg on the negotiated capability.

## Scope

This is the core SEP-2663 surface. The tool runs to completion inline, so a task
is recorded directly as `completed` (the SEP allows any initial status), and
completed tasks live in a pluggable `TaskStore` (`Tasks(store=...)`, in-memory
default) that enforces `default_ttl_ms`. Deferred to follow-ups, each needing
deeper SDK plumbing: background execution (returning `working` tasks), the
in-task `input_required`/`inputResponses` loop over `tasks/update`,
`notifications/tasks`, and SEP-2243 task routing headers.

## Spec

[SEP-2663 — Tasks extension](https://modelcontextprotocol.io/seps/2663-tasks-extension.md)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)

## See also

`apps/` (the additive half of the extension API),
`custom_methods/` (a non-spec method without an extension).
