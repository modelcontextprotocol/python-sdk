# mrtr

Multi-round tool result: on the 2026-07-28 protocol a tool that needs user
input mid-call **returns** `resultType: "input_required"` with embedded
`inputRequests` and an opaque `requestState`, instead of pushing a
server→client request. The client fulfils the embedded requests and retries the
original `tools/call` carrying `inputResponses` and the echoed `requestState`.
The story shows both the `Client` auto-loop (one `await call_tool`, callbacks
fired transparently) and a manual `client.session` loop (the persistable form).

## Run it

```bash
# HTTP — the client self-hosts the server on a free port, runs, then tears it
# down (the InputRequiredResult round-trip is 2026-era only)
uv run python -m stories.mrtr.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.mrtr.client --http --server server_lowlevel
```

## What to look at

- `client.py` `main` — the auto-loop is invisible at the call site:
  `Client(target, mode=mode, elicitation_callback=on_elicit)` then
  `await client.call_tool("deploy", ...)`. The same `on_elicit` callback the
  legacy push path uses is dispatched for each embedded `inputRequests` entry.
- `client.py` manual block — `client.session.call_tool(...,
  allow_input_required=True)` returns the raw `InputRequiredResult` so
  `request_state` can be persisted between rounds; the retry is just another
  `tools/call` with `input_responses=` / `request_state=`.
- `server.py` `deploy` — `ctx.input_responses` / `ctx.request_state` read the
  retry payload; the first round returns
  `InputRequiredResult(input_requests={...}, request_state=...)`, the second
  returns the final string.
- `server_lowlevel.py` — same wire contract via `params.input_responses` /
  `params.request_state` and a hand-built `InputRequiredResult`.

## Caveats

- **Loop bound.** The auto-loop gives up after `input_required_max_rounds`
  (default 10) with `InputRequiredRoundsExceededError`; raise it on the
  `Client` ctor or drop to the manual loop.
- **`requestState` integrity is the server's job.** The client echoes it
  byte-exact and never inspects it; the server MUST treat it as
  attacker-controlled. The SDK ships no signing helper yet.

## Spec

[Input required tool results — server features](https://modelcontextprotocol.io/specification/draft/server/tools#input-required-tool-results)

## See also

`legacy_elicitation/` and `sampling/` — the handshake-era push equivalents this
mechanism replaces on the 2026 protocol. `refund_desk/` — resolver DI at the
MCPServer tier: the questions a tool can declare instead of pushing by hand.
