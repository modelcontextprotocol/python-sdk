# Python SDK examples

- [`stories/`](stories/) — **the canonical reference.** One self-verifying
  example per protocol feature, each with its own README. Start with
  [`stories/tools/`](stories/tools/); the [stories README](stories/README.md)
  has the full table and how to run them.
- [`snippets/`](snippets/) — short extracts embedded into `README.v2.md`. Kept
  minimal and in sync with the top-level README; not intended to be run
  standalone.
- [`servers/everything-server/`](servers/everything-server/) — the conformance
  target for the cross-SDK
  [conformance suite](https://github.com/modelcontextprotocol/conformance).
  Exercises every server capability in one process.
- [`mcpserver/`](mcpserver/) — single-file v1-era examples retained for the
  migration guide; superseded by `stories/` and slated for removal.

For real-world servers see the
[servers repository](https://github.com/modelcontextprotocol/servers).
