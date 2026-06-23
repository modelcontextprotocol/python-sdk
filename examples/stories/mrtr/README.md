# mrtr

Multi-round tool results: a 2026-era tool call returns
`resultType: "input_required"` with a `requestState` HMAC instead of pushing an
`elicitation/create` request. The client fulfils the input and resubmits, and
the server resumes from the carried state. The story will show both the
auto-fulfil helper and a manual resubmit loop.

**Status: not yet implemented** ([#2898](https://github.com/modelcontextprotocol/python-sdk/issues/2898)).
The `InputRequiredResult` types exist, but `Client.call_tool` still validates
the response as a plain `CallToolResult` and rejects `input_required`. There is
no runnable round-trip until the runtime lands.

## Spec

[Multi-round tool results — server features](https://modelcontextprotocol.io/specification/draft/server/tools#multi-round-results)

## Working example elsewhere

The TypeScript SDK ships a runnable `mrtr` story:
[typescript-sdk/examples/mrtr](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/mrtr).

## See also

`elicitation/` and `sampling/` — the handshake-era push equivalents that this
mechanism replaces on the 2026 protocol.
