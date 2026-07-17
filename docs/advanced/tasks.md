# Tasks

A **task** is a `tools/call` answered by reference: instead of the `CallToolResult`,
the server returns a `CreateTaskResult` carrying a task id, and the client fetches
the outcome with `tasks/get`. That is
[SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension.md), and the SDK
ships it as the built-in `Tasks` extension (`io.modelcontextprotocol/tasks`).
If [Extensions](extensions.md) are new to you, skim that page first. One minute,
then come back.

## Opting in, both sides

```python title="server.py" hl_lines="6 16 17"
--8<-- "docs_src/tasks/tutorial001.py"
```

* `extensions=[Tasks()]`: the server advertises `io.modelcontextprotocol/tasks`
  under `capabilities.extensions` and serves `tasks/get`, `tasks/update`, and
  `tasks/cancel`.
* `Client(mcp, extensions=[TasksExtension()])`: the client declares the extension
  back — `TasksExtension` (from `mcp.client`) is the client half, a
  `ClientExtension` whose result claim admits and resolves the `task`
  resultType on `tools/call`. Only a declaring client's `tools/call` may be
  answered with a task.
* `client.call_tool(...)` does not change. When the answer comes back as a
  `CreateTaskResult`, the client polls `tasks/get` — honoring the server's
  `pollIntervalMs` hint, one second between polls in its absence — and surfaces
  only the final `CallToolResult`. A `failed` task raises the typed
  `TaskFailedError` carrying the inlined JSON-RPC error; a `cancelled` one raises
  `TaskCancelledError`; an `input_required` one raises `TaskInputRequiredError` —
  the automatic in-task input loop is not implemented yet, so drive that task
  manually (below). All three subclass `TaskError`, so one `except TaskError`
  catches any non-completion.

Degradation is built in. A modern client that does not declare the extension is
never augmented: it keeps getting plain `CallToolResult`s. And a legacy
(2025-11-25) connection cannot negotiate the extension at all — the capability
rides `server/discover`, which a legacy handshake doesn't have — so for that
client the feature does not exist. Your tools don't change either way.

## The server decides

Augmentation is the server's call, per request: the client's declaration is
permission, not a trigger. `Tasks()` augments every call from a declaring client;
pass `augment=` to be choosier:

```python title="server.py" hl_lines="9-10 13"
--8<-- "docs_src/tasks/tutorial002.py"
```

* `augment` sees the validated `CallToolRequestParams` for each call. Return
  `False` and the call passes through untouched, exactly as for a non-declaring
  client — errors included. Here `transcode` becomes a task; `ping` never does.
* `default_ttl_ms` bounds retention. It is stamped on the wire as `ttlMs`, and the
  record is dropped once the deadline passes. The default `None` retains records
  for the store's lifetime.
* `clock` (not shown) injects the source of time behind the wire timestamps and
  TTL deadlines. Inject a fixed clock for deterministic tests.

## Where tasks live

Records persist through a `TaskStore`, a two-method protocol:

```python
class TaskStore(Protocol):
    async def put(self, record: TaskRecord) -> None: ...
    async def get(self, task_id: str) -> TaskRecord | None: ...
```

The default `InMemoryTaskStore` is **per-process**: right for stdio servers and
single-process development, wrong for a multi-worker HTTP deployment. SEP-2663
requires a task to be durably recorded before its `CreateTaskResult` is returned,
and a poll routed to another worker must find it — back `Tasks(store=...)` with
shared storage there. `get` returning `None` is the whole expiry contract: unknown
and expired ids look identical, and both answer `-32602` on the wire.

Task ids are unguessable bearer capabilities (at least 128 bits of entropy): any
caller presenting a valid id may poll the task, which is what lets a reconnecting
client resume. Need stricter scoping or audited access? That is a custom store's
job.

## What execution actually looks like

In this SDK the tool still runs **inline**, to completion, inside the `tools/call`
request. A task is therefore born terminal:

* The tool produced a result → a `completed` task, with the `CallToolResult`
  inlined on `tasks/get`. A result with `isError: true` is still `completed`;
  tool-level failure is a result, not a protocol error.
* The call raised a JSON-RPC error (an `MCPError`) → a `failed` task, with the
  error inlined on `tasks/get`. The declaring client receives a failed
  `CreateTaskResult` instead of the JSON-RPC error, and the transparent driver
  turns it into `TaskFailedError`.
* `tasks/cancel` and `tasks/update` acknowledge and change nothing: cancellation
  is cooperative in SEP-2663, and here the work has always finished before a
  `tasks/*` request can arrive.

A [multi-round-trip](../handlers/multi-round-trip.md) interim (`input_required`) passes through
un-augmented: the exchange resolves on the original `tools/call`, and only the leg
that produces the final result becomes a task.

What augmentation buys today is the wire shape and the retention: the result of an
expensive call outlives the request that computed it, fetchable by id for `ttlMs`.
Background execution is on the roadmap (below).

## Driving the task yourself

The transparent flow is a convenience, not a requirement. Drop one layer to get the
`CreateTaskResult`, then drive `tasks/*` with the typed functions in
`mcp.client.tasks`:

```python title="client.py" hl_lines="19 24 29"
--8<-- "docs_src/tasks/tutorial003.py"
```

* `session.call_tool(..., allow_claimed=True)` returns the typed
  `CreateTaskResult` instead of polling. Without the flag, an unexpected
  `CreateTaskResult` raises `RuntimeError` rather than leaking the widened union
  into code that expected a `CallToolResult`.
* `get_task` is one `tasks/get`: it returns the `GetTaskResult` snapshot —
  `result` is set on a `completed` task, `error` on a `failed` one, never both.
* `wait_task` polls to a terminal status and returns the final `CallToolResult`,
  raising the same typed errors as the transparent flow. Pass the
  `CreateTaskResult` and its `pollIntervalMs` hint seeds the cadence — or pass a
  bare task id: task ids are bearer capabilities (above), so a client that
  reconnected, or restarted with nothing but the persisted id, can resume a task
  it no longer holds the `CreateTaskResult` for.
* `update_task` answers a task's in-task `inputRequests`, and `cancel_task` asks
  the server to stop one. Both hide the empty acknowledgement and return `None`.
  Cancellation is cooperative in SEP-2663 — it may never take effect, and in this
  SDK the work has always finished already — so follow with `get_task` for the
  status that actually resulted.

## Who sees what

| Caller | `tools/call` | `tasks/*` |
|---|---|---|
| Declaring 2026-07-28 client | may be augmented into a task | served |
| Non-declaring 2026-07-28 client | plain `CallToolResult`, always | `-32021` missing required client capability |
| Legacy (2025-11-25) connection | plain `CallToolResult`, always | `-32601` method not found |

The split on `tasks/*` is deliberate. A modern client could fix its declaration, so
it gets the capability error with the machine-readable `requiredCapabilities`
payload; a legacy client could not, so for it the methods simply don't exist. A
declaring client naming an unknown — or expired — task id gets `-32602` (invalid
params).

Over Streamable HTTP, every `tasks/*` request carries the `Mcp-Name: <taskId>`
routing header (SEP-2663 via SEP-2243) so intermediaries can route the poll to the
instance holding the task's state. The SDK stamps it client-side and validates it
server-side; you never touch it.

## Roadmap

This is the core SEP-2663 surface. Background execution (tasks created `working`
and resolved later), the in-task `input_required` loop over `tasks/update`, and
`notifications/tasks` over `subscriptions/listen` build on it as planned
follow-ups — each needs deeper SDK plumbing, and the wire contract above is
already shaped for them.
