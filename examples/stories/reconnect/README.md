# reconnect

Probe `server/discover` once, persist the `DiscoverResult`, and reconnect with
**zero round-trips**. The first client connects at `mode="auto"` (one
`server/discover` request inside `__aenter__`); a second client at
`mode=LATEST_MODERN_VERSION, prior_discover=<cached>` enters with no wire
traffic and has `server_info` / `server_capabilities` available immediately.

## Run it

```bash
# over HTTP — Streamable HTTP only; in-memory has no "round-trip" to skip.
# The client self-hosts the server on a free port, runs, then tears it down.
uv run python -m stories.reconnect.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.reconnect.client --http --server server_lowlevel
```

## What to look at

- `client.py` — the first `Client(targets(), mode="auto")`. The `mode="auto"`
  connect ladder runs `server/discover` inside `__aenter__`;
  `client.session.discover_result` is the cached result. Round-trip it through
  `model_dump_json()` / `DiscoverResult.model_validate_json()` to model an
  on-disk cache.
- `client.py` — `Client(targets(), mode=LATEST_MODERN_VERSION,
  prior_discover=rehydrated)`. A version pin plus a prior `DiscoverResult`
  installs the cached state via `ClientSession.adopt()` with no `initialize`
  and no `server/discover` on the wire — the era-neutral `client.server_info` /
  `.server_capabilities` accessors are populated before the first request.
- `client.py` — `targets()`. A `Client` cannot be re-entered after exit; each
  call yields a fresh target against the same server, so the reconnect is a
  genuinely new connection.

## Caveats

- `mode=<version-pin>` *without* `prior_discover=` synthesizes a placeholder
  whose `server_info` is `Implementation(name="", version="")`. Pass the cached
  result to get real identity on reconnect. Whether `Client` should expose a
  public synthesizer (or refuse the bare pin) is open.
- `client.session.discover_result` is a one-hop reach into the mechanics layer;
  `Client` does not yet surface the cached result directly.
- The wire-level proof that the second entry sends zero requests lives in the
  interaction suite (`test_prior_discover_populates_state_with_zero_connect_time_traffic`);
  this story asserts only what's observable through the public `Client`
  surface.

## Spec

- [`server/discover`](https://modelcontextprotocol.io/specification/draft/server/discover)
- [Versioning — backward compatibility](https://modelcontextprotocol.io/specification/draft/basic/versioning)

## See also

`dual_era/` (auto-discover + era-neutral accessors), `parallel_calls/` (the
other multi-connection client).
