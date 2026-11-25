# caching

A server stamps `CacheableResult` hints (`ttl_ms`, `cache_scope`) onto list and
read responses; a client honours them to skip redundant round-trips. The story
will show per-result overrides on `@mcp.resource()` / `@mcp.tool()` and the
client-side cache hit/miss path.

**Status: not yet implemented.** Server-side stamping landed (defaults
`ttl_ms=0`, `cache_scope="private"`), but the per-result override hook and the
client honouring path are not implemented yet. An example today could only show
the defaults being emitted, not acted on.

## Spec

[Caching — basic utilities](https://modelcontextprotocol.io/specification/draft/basic/utilities/caching)

## Working example elsewhere

The TypeScript SDK ships a runnable `caching` story:
[typescript-sdk/examples/caching](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/caching).
