# Python SDK examples

- [`stories/`](stories/) — **the canonical reference.** One self-verifying
  example per protocol feature, each with its own README. Start with
  [`stories/tools/`](stories/tools/); the [stories README](stories/README.md)
  has the full table and how to run them.
- [`snippets/`](snippets/) — short extracts that were embedded into the v1
  README (now on the `v1.x` branch); superseded by `docs_src/`, which the docs
  and README embed today. Retained pending consolidation into `stories/`.
- [`servers/everything-server/`](servers/everything-server/) — the conformance
  target for the cross-SDK
  [conformance suite](https://github.com/modelcontextprotocol/conformance).
  Exercises every server capability in one process.
- [`servers/todos-server/`](servers/todos-server/) — the reference server: a
  small todo board where every server-side feature has a real job, serving
  both protocol revisions over stdio and Streamable HTTP. A faithful port of
  the TypeScript SDK's `examples/todos-server`.
- [`mcpserver/`](mcpserver/) — single-file v1-era examples retained for the
  migration guide; superseded by `stories/` and slated for removal.
- [`clients/`](clients/) and the remaining [`servers/`](servers/) directories
  (`simple-*`, `sse-polling-demo`, `structured-output-lowlevel`) — standalone
  v1-era projects retained pending consolidation into `stories/` (the
  `simple-auth` pair is still linked from `docs/run/authorization.md` and `docs/client/oauth-clients.md`).

For real-world servers see the
[servers repository](https://github.com/modelcontextprotocol/servers).
