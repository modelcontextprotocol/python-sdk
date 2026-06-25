# legacy-elicitation

> **Legacy mechanism (2025 handshake era).** This story shows the push-style
> server→client `elicitation/create` request; the 2026-07-28 protocol carries
> elicitation as an `InputRequiredResult` round-trip instead — that path is the
> [`mrtr/`](../mrtr/) story. Elicitation itself is **not** deprecated.
> TODO(maxisbey): unify once the MRTR runtime lands
> ([#2898](https://github.com/modelcontextprotocol/python-sdk/issues/2898)).

A tool pauses mid-call to ask the user for structured input. On the
handshake-era protocol the server pushes an `elicitation/create` *request* to
the client and blocks until the client's `elicitation_callback` answers
`accept` / `decline` / `cancel`. Two modes: **form** (`ctx.elicit(message,
PydanticModel)` — schema derived from the model, accepted content validated
back into it) and **url** (`ctx.elicit_url(...)` — directs the user out-of-band
for OAuth / payment flows; `send_elicit_complete` notifies the client when the
flow finishes).

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.legacy_elicitation.client

# against a running HTTP server (--legacy: the push request needs the handshake era)
uv run python -m stories.legacy_elicitation.server --http --port 8000 &
uv run python -m stories.legacy_elicitation.client --http http://127.0.0.1:8000/mcp --legacy
```

## What to look at

- `client.py` `main` — the whole client setup is one visible construction:
  `Client(target, mode=mode, elicitation_callback=on_elicit)`. Supplying
  `elicitation_callback` is what advertises the `elicitation: {form, url}`
  capability; `on_elicit` serves *both* modes by branching on
  `isinstance(params, ElicitRequestURLParams)`.
- `server.py` `register_user` — `await ctx.elicit("...", Registration)` derives
  the form schema from the pydantic model and returns a typed
  `ElicitationResult[Registration]`; narrow with `isinstance(answer,
  AcceptedElicitation)` before reading `answer.data`.
- `server.py` `link_account` — `ctx.elicit_url(...)` for out-of-band flows;
  after the user finishes, `send_elicit_complete` emits
  `notifications/elicitation/complete` so the client can correlate.
- `server_lowlevel.py` — the same flow via `ctx.session.elicit_form` /
  `ctx.session.elicit_url` and a hand-written `requestedSchema`.

## Caveats

- **Context paths.** `ctx.elicit` / `ctx.elicit_url` and the 2-hop
  `ctx.request_context.session.send_elicit_complete` are interim; a later
  release will shorten these.
- **No per-mode opt-in.** Supplying any `elicitation_callback` advertises both
  form and url support; there is currently no way to advertise form-only from
  `Client`.
- **Throw-style URL elicitation** (`raise UrlElicitationRequiredError([...])` →
  wire `-32042`) is the stateless-transport alternative to `ctx.elicit_url`;
  see `tests/interaction/lowlevel/test_elicitation.py` and the `error_handling`
  story.

## Spec

[Elicitation — client features](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)

## See also

`sampling/` (same push-request shape, deprecated per SEP-2577), `mrtr/`
(planned — the 2026-era carrier), `error_handling/`
(`UrlElicitationRequiredError`).
