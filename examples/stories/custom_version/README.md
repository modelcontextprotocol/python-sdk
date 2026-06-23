# custom-version

Where the negotiated protocol version lives after the 2025-era `initialize`
handshake: `client.protocol_version` on the client, and
`ctx.request_context.protocol_version` (or `ctx.protocol_version` directly on
`ServerRequestContext` in the lowlevel API) inside a handler. The scenario
proves both sides agree by round-tripping the server's view through a tool
call and comparing it to the client's accessor.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.custom_version.client

# against a running HTTP server
uv run python -m stories.custom_version.server --http --port 8000 &
uv run python -m stories.custom_version.client --http http://127.0.0.1:8000/mcp --legacy
```

## What to look at

- `server.py` — `ctx.request_context.protocol_version`: the version the
  `initialize` handshake settled on, available to every handler.
- `server_lowlevel.py` — `ctx.protocol_version`: the same field directly on
  `ServerRequestContext`.
- `client.py` — `client.protocol_version`: the era-neutral accessor (populated
  whether the connection used `initialize` or `server/discover`).

## Not yet: overriding the supported-version set

The TypeScript SDK lets a server declare `supportedProtocolVersions: [...]` to
accept a version string the SDK doesn't yet ship (the first entry is the
counter-offer when the client requests something unknown). The python-sdk
doesn't expose this knob yet — server-side negotiation is fixed to
`mcp.shared.version.HANDSHAKE_PROTOCOL_VERSIONS`. When that kwarg lands,
`build_server()` grows one argument and `scenario()` asserts a custom version
round-trips. Tracked for pre-beta.

## Spec

[Lifecycle — version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)

## See also

`dual_era/` (one server serving both eras), `legacy_routing/` (HTTP-layer era
classifier).
