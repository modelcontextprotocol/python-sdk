# tasks

Task-augmented execution: a requestor augments a `tools/call` with a `task`, the
receiver returns a `CreateTaskResult` immediately, and the requestor polls
`tasks/get` and retrieves the deferred result.

**Status: deferred.** Tasks ship in 2026-07-28 as
[SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/seps/2663-tasks-extension.md),
an `io.modelcontextprotocol/tasks` extension that is wire-incompatible with the
2025-11-25 in-core design still carried (types-only) in `mcp_types`. The runtime
needs to be built to the SEP — server-decided augmentation (ignoring the legacy
`params.task`), the `{tasks/get, tasks/update, tasks/cancel}` method set, the
`resultType: "task"` envelope, `execution.taskSupport` gating, and `ttlMs`
fields — so it lands in a separate PR with the conformance `tasks-*` scenarios
wired in.

## Spec

[SEP-2663 — Tasks extension](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/seps/2663-tasks-extension.md)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)

## See also

`apps/` (the additive half of the extension API).
