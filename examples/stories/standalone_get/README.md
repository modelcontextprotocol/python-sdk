# standalone-get

Server-initiated `notifications/resources/list_changed` delivered over the
**standalone GET SSE stream** of a sessionful Streamable-HTTP connection. The
`add_note` tool mutates the resource list and emits the notification with no
related request; the client's `message_handler` receives it on the GET stream,
awaits it on an `anyio.Event`, then re-lists to observe the change.

## Run it

```bash
# server (HTTP-only — the standalone GET stream is a Streamable-HTTP feature)
uv run python -m stories.standalone_get.server --http --port 8000 &
# client
uv run python -m stories.standalone_get.client --http http://127.0.0.1:8000/mcp --legacy
```

## What to look at

- **`server.py` — `await ctx.session.send_resource_list_changed()`.**
  `MCPServer.add_resource` does **not** auto-emit (unlike the TypeScript SDK's
  `registerResource`); the explicit call is the teaching point. Because
  `send_*_list_changed()` carries no `related_request_id`, the only route to the
  client is the standalone GET stream.
- **`client.py` — `message_handler=` + `anyio.Event`.** The notification is not
  guaranteed to arrive before the tool result (different streams), so the
  scenario `await`s an event the handler sets, bounded by `anyio.fail_after(5)`.
  `client_kw()` is a callable so each run wires a fresh `anyio.Event` into
  `message_handler`.

## Caveats

- **Legacy-era only.** The standalone GET stream is a sessionful 2025-era
  transport feature; in 2026-07-28 these notifications travel on a
  `subscriptions/listen` stream instead — not yet wired in this SDK
  ([#2901](https://github.com/modelcontextprotocol/python-sdk/issues/2901)).
- DNS-rebinding protection is disabled via `transport_security=NO_DNS_REBIND`
  because the in-process httpx client sends no `Origin` header. Drop the kwarg
  for a real deployment.
- Neither `MCPServer` nor lowlevel `Server` auto-advertises
  `resources.listChanged: true` in capabilities, and `MCPServer` exposes no knob
  to set it. A spec-conformant client that gates on the capability flag would
  skip the handler.
- `ctx.session.*` is the interim path; a later release will shorten it.
- Tool-triggered, not timer-driven, for harness determinism. "Server pushes on
  its own schedule" is not demonstrated.

## Spec

[List Changed Notification](https://modelcontextprotocol.io/specification/2025-11-25/server/resources#list-changed-notification),
[Streamable HTTP — Listening for Messages](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#listening-for-messages-from-the-server)

## See also

`stickynotes/` (list_changed inside a feature capstone), `sse_polling/` (the
other GET-stream story — resumability), `json_response/` (what happens when the
server can't stream).
