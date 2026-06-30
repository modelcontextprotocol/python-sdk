# mrtr

Multi-round tool result: on the 2026-07-28 protocol a tool that needs user
input mid-call **returns** `resultType: "input_required"` with embedded
`inputRequests` and an opaque `requestState`, instead of pushing a
server→client request. The client fulfils the embedded requests and retries the
original `tools/call` carrying `inputResponses` and the echoed `requestState`.
The story shows both the `Client` auto-loop (one `await call_tool`, callbacks
fired transparently) and a manual `client.session` loop (the persistable form)
— and, because `requestState` round-trips through the client, the security
surface that protects it: the server is constructed with
`request_state_security=RequestStateSecurity.ephemeral()`, handlers keep
writing plaintext state, and the SDK seals it at the wire boundary. The manual
loop tampers with the sealed token to show what a forged echo gets back.

## Run it

```bash
# HTTP — the client self-hosts the server on a free port, runs, then tears it
# down (the InputRequiredResult round-trip is 2026-era only)
uv run python -m stories.mrtr.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.mrtr.client --http --server server_lowlevel
```

## What to look at

- `server.py` `build_server` — the whole security opt-in is one constructor
  argument: `request_state_security=RequestStateSecurity.ephemeral()`.
  Opting in is this server's choice — only tools with `Resolve(...)`
  parameters are required to configure protection; a hand-built flow like
  `deploy` would otherwise send its state across the wire as plaintext.
  `ephemeral()` generates a key at process start, which is right for a
  single-process server like this one; a fleet (multi-worker or load-balanced)
  shares keys with `RequestStateSecurity(keys=[...])` so any instance can
  verify state another minted.
- `server.py` `deploy` — handlers stay plaintext: the first round returns
  `InputRequiredResult(input_requests={...},
  request_state="awaiting-confirm")` and the retry asserts
  `ctx.request_state == "awaiting-confirm"`. The tool never touches the
  crypto; the boundary seals on the way out and unseals the echo on the way
  back in.
- `client.py` `main` — the auto-loop is invisible at the call site:
  `Client(target, mode=mode, elicitation_callback=on_elicit)` then
  `await client.call_tool("deploy", ...)`. The same `on_elicit` callback the
  legacy push path uses is dispatched for each embedded `inputRequests` entry.
- `client.py` manual block — `client.session.call_tool(...,
  allow_input_required=True)` returns the raw `InputRequiredResult` so
  `request_state` can be persisted between rounds. The wire value is an opaque
  sealed token, **not** the string the server code wrote — the client asserts
  exactly that, then retries with one character of the token flipped and gets
  the single frozen error every verification failure maps to: `-32602`,
  `"Invalid or expired requestState"`, `{"reason": "invalid_request_state"}`.
  The specific reason (tampered tag, expiry, wrong request, wrong principal)
  appears only in the server's log, never on the wire. The untampered token
  then completes the round normally.
- `server_lowlevel.py` — the lowlevel tier has no construction-time
  requirement; the same enforcement is one appended middleware:
  `server.middleware.append(RequestStateBoundary(RequestStateSecurity.ephemeral()))`.

## Caveats

- **Loop bound.** The auto-loop gives up after `input_required_max_rounds`
  (default 10) with `InputRequiredRoundsExceededError`; raise it on the
  `Client` ctor or drop to the manual loop.
- **`ephemeral()` dies with the process.** The key is generated at startup and
  held only in memory, so a server restart (or a retry landing on a different
  instance) invalidates in-flight rounds: the client gets the same frozen
  rejection and must start the flow over. Use
  `RequestStateSecurity(keys=[...])` when state must survive either.

## Spec

[Input required tool results — server features](https://modelcontextprotocol.io/specification/draft/server/tools#input-required-tool-results),
[Multi-round-trip requests — security patterns](https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr)

## See also

`legacy_elicitation/` and `sampling/` — the handshake-era push equivalents this
mechanism replaces on the 2026 protocol. `refund_desk/` — resolver DI at the
MCPServer tier: the questions a tool can declare instead of pushing by hand
(its elicited answers ride in the same sealed `requestState`).
