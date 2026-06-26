# tasks

The `io.modelcontextprotocol/tasks` extension: long-running work registered
with `@task`, polled via `tasks/get`, updated mid-flight, and cancelled with
`tasks/cancel`. The story will show a task that outlives the request that
started it.

**Status: not yet implemented.** The extension types exist but the `extensions`
capability map is not yet surfaced on `MCPServer`, and the runtime trails the
release. The TypeScript SDK deliberately removed its tasks example pending the
same work.

## Spec

[Tasks — basic utilities](https://modelcontextprotocol.io/specification/draft/basic/utilities/tasks)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)
