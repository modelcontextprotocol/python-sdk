# mrtr

Multi-round tool results: a 2026-era tool call returns
`resultType: "input_required"` with a `requestState` HMAC instead of pushing an
`elicitation/create` request. The client fulfils the input and resubmits, and
the server resumes from the carried state. The story will show both the
auto-fulfil helper and a manual resubmit loop.

**Status: not yet implemented** ([#2898](https://github.com/modelcontextprotocol/python-sdk/issues/2898)).
The lowlevel registration surface exists on `main` as of
[#2967](https://github.com/modelcontextprotocol/python-sdk/pull/2967)
(`ae13ede`), which widened the tool/prompt/resource handler return types to
include `InputRequiredResult`. This story graduates from a README stub to a
runnable example once this branch's base includes that commit.

## Spec

[Multi-round tool results — server features](https://modelcontextprotocol.io/specification/draft/server/tools#multi-round-results)

## Working example elsewhere

The TypeScript SDK ships a runnable `mrtr` story:
[typescript-sdk/examples/mrtr](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/mrtr).

## See also

`legacy_elicitation/` and `sampling/` — the handshake-era push equivalents that
this mechanism replaces on the 2026 protocol. The TypeScript SDK ships a single
dual-era `elicitation/` story covering both eras in one place; we re-merge
`legacy_elicitation/` back into `elicitation/` once MRTR lands.
