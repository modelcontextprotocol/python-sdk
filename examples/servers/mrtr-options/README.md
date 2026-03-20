# MRTR handler-shape options (SEP-2322)

Python-SDK counterpart to [typescript-sdk#1701]. Seven ways to write the same
weather-lookup tool, so the diff between files is the argument.

Unlike the TS demos, the lowlevel plumbing here is **real** — each option is
an actual `mcp.server.Server` that round-trips `IncompleteResult` through the
wire protocol. The invariant test at the bottom asserts they all produce
identical client-observed behaviour.

[typescript-sdk#1701]: https://github.com/modelcontextprotocol/typescript-sdk/pull/1701

## Start here

If you just want to see what an MRTR lowlevel handler looks like without
the comparison framing, read these first:

- [`basic.py`](mrtr_options/basic.py) — the simple-tool equivalent. One
  `IncompleteResult`, one retry, done. ~130 lines, half of which are
  comments explaining the two moves every MRTR handler makes.
- [`basic_multiround.py`](mrtr_options/basic_multiround.py) — the
  ADO-rules SEP example. Two rounds, with `request_state` carrying
  accumulated context across the retry so any server instance can
  handle any round.

Both are runnable end-to-end against the in-memory client:

```sh
uv run python -m mrtr_options.basic
uv run python -m mrtr_options.basic_multiround
```

## The quadrant

| Server infra                    | Pre-MRTR client                   | MRTR client |
| ------------------------------- | --------------------------------- | ----------- |
| Can hold SSE                    | E by default; A/C/D if you opt in | MRTR        |
| MRTR-only (horizontally scaled) | E by necessity                    | MRTR        |

Both rows *work* for old clients — version negotiation succeeds,
`tools/list` is complete, tools that don't elicit are unaffected. Only
elicitation inside a tool is unavailable. Bottom-left isn't "unresolvable";
it's "E is the only option." Top-left is "E, unless you choose to carry SSE
infra." The rows collapse for E, which is why it's the SDK default.

## Options

|                                | Author writes                   | SDK does                         | Hidden re-entry | Server state         | Old client gets                   |
| ------------------------------ | ------------------------------- | -------------------------------- | --------------- | -------------------- | --------------------------------- |
| [E](mrtr_options/option_e_degrade.py)        | MRTR-native only                | Nothing                          | No              | None                 | Result w/ default, or error       |
| [A](mrtr_options/option_a_sse_shim.py)       | MRTR-native only                | Retry-loop over SSE              | Yes, safe       | SSE connection       | Full elicitation                  |
| [B](mrtr_options/option_b_await_shim.py)     | `await elicit()`                | Exception → `IncompleteResult`   | **Yes, unsafe** | None                 | Full elicitation                  |
| [C](mrtr_options/option_c_version_branch.py) | One handler, `if version` branch | Version accessor                | No              | SSE (old-client arm) | Full elicitation                  |
| [D](mrtr_options/option_d_dual_handler.py)   | Two handlers                    | Picks by version                 | No              | SSE (old-client arm) | Full elicitation                  |
| [F](mrtr_options/option_f_ctx_once.py)       | MRTR-native + `ctx.once` wraps  | `once()` guard in request_state  | No              | None                 | (same as E)                       |
| [G](mrtr_options/option_g_tool_builder.py)   | Step functions + `.build()`     | Step-tracking in request_state   | No              | None                 | (same as E)                       |
| [H](mrtr_options/option_h_linear.py)         | `await ctx.elicit()` (linear)   | Holds coroutine frame in memory  | No              | Coroutine frame      | (same as E)                       |

"Hidden re-entry" = the handler function is invoked more than once for a
single logical tool call, and the author can't tell from the source text.

**A is safe** because MRTR-native code has the re-entry guard (`if not
prefs: return IncompleteResult(...)`) visible in source even though the
*loop* is hidden.

**B is unsafe** because `await elicit()` looks like a suspension point but
is actually a re-entry point on MRTR sessions — see the `audit_log`
landmine in that file.

## Footgun prevention (F, G)

A–E are about the dual-path axis (old client vs new). F and G address a
different axis: even in a pure-MRTR world, the naive handler shape has a
footgun. Code above the `if not prefs` guard runs on every retry. If that
code is a DB write or HTTP POST, it executes N times for N-round
elicitation. Nothing *enforces* putting side-effects below the guard —
safety depends on the developer knowing the convention. The analogy from
SDK-WG review: the naive MRTR handler is de-facto GOTO.

**F (`MrtrCtx.once`)** keeps the monolithic handler but wraps side-effects
in an idempotency guard. `ctx.once("audit", lambda: audit_log(...))` checks
`request_state` — if the key is marked executed, skip. Opt-in: an unwrapped
mutation still fires twice. The footgun is made *visually distinct*, which
is reviewable.

**G (`ToolBuilder`)** decomposes the handler into named step functions.
`incomplete_step` may return `IncompleteResult` or data; `end_step` receives
everything and runs exactly once. There is no "above the guard" zone because
there is no guard — the SDK's step-tracking is the guard. Side-effects go in
`end_step`, structurally unreachable until all elicitations complete.

Both depend on `request_state` integrity. The demos use plain base64-JSON;
a real SDK MUST HMAC-sign the blob, or the client can forge step-done
markers and skip the guards. Per-session key derived from `initialize` keeps
it stateless. Without signing, the safety story is advisory.

## Trade-offs

**E is the SDK default.** A horizontally-scaled server gets E for free —
it's the only thing that works on that infra. A server that can hold SSE
also gets E by default, and opts into A/C/D only if serving old-client
elicitation is worth the extra infra dependency.

**A vs E** is the core tension. Same author-facing code (MRTR-native), the
only difference is whether old clients get elicitation. A requires shipping
`sse_retry_shim`; E requires nothing. A also carries a deployment-time
hazard E doesn't: the shim calls real SSE under the hood, so on MRTR-only
infra it fails at runtime when an old client connects — a constraint that
lives nowhere near the tool code.

**B** is zero-migration but breaks silently for anything non-idempotent
above the await. Not a ship target.

**C vs D** is factoring: one function with a branch vs two functions with a
dispatcher. Both put the dual-path burden on the tool author.

**F vs G** is the footgun-prevention trade. F is minimal — one line per
side-effect, composes with any handler shape. G is structural —
double-execution impossible for `end_step`, but costs two function defs
per tool. Likely SDK answer: ship F as a primitive on the context, ship G
as an opt-in builder, recommend G for multi-round tools and F for
single-question tools.

**H (linear continuation)** is the Option B footgun, *fixed*. Handler code
reads exactly like the SSE era — `await ctx.elicit()` is a genuine
suspension point, side-effects above it fire once — because the coroutine
frame is held in memory across rounds. The trade: server is stateful
*within* a single tool call (frame keyed by `request_state`), so
horizontally-scaled deployments need sticky routing on the token. Same
operational shape as A's SSE hold but without the long-lived connection.
Use for migrating existing SSE-era tools without rewriting, or when the
linear style is genuinely clearer than guard-first. Don't use if you need
true statelessness — E/F/G encode everything in `request_state` itself.

## The invariant test

`tests/server/experimental/test_mrtr_options.py` parametrises all seven
servers against the same `Client` + `elicitation_callback`, asserting
identical output. The footgun test measures `audit_count` to prove F and G
hold the side-effect to one.

## Not in scope

- Persistent/Tasks workflow — `ServerTaskContext` already does
  `input_required`; MRTR integration is a separate PR
- `mrtrOnly` client flag — trivial to add, not demoed
- requestState HMAC signing — called out in code comments
