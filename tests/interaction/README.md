# Interaction-model test suite

This suite enumerates the MCP interaction model as end-to-end tests: one test per piece of
functionality, asserting the full client↔server round trip through the public API. It exists to
pin the SDK's observable behaviour — every request type, every notification direction, every
error plane — so that internal rewrites of the send/receive path can be proven equivalent by
running the suite before and after.

```bash
uv run --frozen pytest tests/interaction/
```

The whole suite is in-memory and event-driven; it runs in about a second.

## Ground rules

- **Public API only.** Tests drive a `Client` connected to a `Server` or `MCPServer`. Nothing
  reaches into session internals, so the suite keeps working when those internals change.
  `ClientSession` is used directly only for behaviours `Client` cannot express (skipping
  initialization, requesting a non-default protocol version).
- **Pin current behaviour.** Every test passes against the current `main`, including behaviours
  that diverge from the specification. A failing or xfailed test proves nothing about whether a
  rewrite preserved behaviour; a passing test that pins the wrong output exactly does. Known
  divergences are recorded as data on the requirement (see below), not worked around in the test.
- **Spec-mandated assertions, not implementation quirks.** Error *codes* are asserted against
  the constants in `mcp.types`; error *message strings* are pinned only where they are the
  SDK's own deliberate output.
- **No sleeps, no real I/O.** Concurrency is coordinated with `anyio.Event`; every wait that
  could hang is bounded by `anyio.fail_after(5)`. The streamable HTTP tests drive the Starlette
  app in-process through the suite's streaming ASGI bridge (`transports/_bridge.py`), which
  delivers each response chunk as the server produces it — full duplex, but still no sockets,
  threads, or subprocesses anywhere.

## Layout

```text
tests/interaction/
  _requirements.py      the requirements manifest (see below)
  _helpers.py           shared type aliases + the wire-recording transport
  _connect.py           the transport-parametrized connection factories
  conftest.py           the connect fixture (the transport matrix)
  test_coverage.py      enforces the manifest ↔ test contract
  lowlevel/             one file per feature area, against the low-level Server
  mcpserver/            the same feature areas in MCPServer's natural idiom
  transports/           behaviour specific to one transport (modes, streams, framing)
```

The two server APIs produce genuinely different wire output for the same conceptual feature
(`MCPServer` generates schemas, converts exceptions to `isError` results, attaches structured
content), so they get parallel directories with mirrored file names rather than one parametrized
test body — each directory pins its flavour's true output exactly.

### The transport matrix

Transport-agnostic tests take the `connect` fixture instead of constructing `Client(server)`
directly, and therefore run once per transport: over the in-memory transport and over the
server's real streamable HTTP app driven in process through the streaming bridge. A test connects
the same way in either case — `async with connect(server, ...) as client:` — and asserts the same
output, because the transport is not supposed to change observable behaviour. Tests that are tied
to one transport do not use the fixture: the wire-recording tests (their seam is the in-memory
stream pair), the bare-`ClientSession` lifecycle tests, the real-clock timeout tests (the timeout
machinery is transport-independent and must not race transport latency), and everything under
`transports/`, which pins behaviour only observable on that transport.

A transport conformance test in `transports/` speaks raw `httpx` against the mounted ASGI app
**only** when its assertion is about HTTP semantics that `Client` cannot observe — status codes,
response headers, SSE event fields, which stream a message travels on. Any other behaviour is
asserted through a `Client`, connected to the mounted app via `client_via_http(http)` so several
clients can share one session manager.

## The requirements manifest

`_requirements.py` maps every behaviour the suite covers to the reason it must hold:

```python
"tools:call:content:text": Requirement(
    source=f"{SPEC_BASE_URL}/server/tools#text-content",
    behavior="tools/call delivers arguments to the tool handler and returns its text content.",
),
```

- **`source`** is a deep link into the MCP specification for externally mandated behaviour,
  the literal string `"sdk"` for behaviour the SDK chose where the spec is silent, or
  `"issue:#n"` for a regression lock.
- **`behavior`** describes the *required* behaviour — what the specification (or the SDK's own
  contract) says should happen. Tests always pin the SDK's current behaviour; where that falls
  short of `behavior`, the gap is recorded as data rather than hidden in the test.
- **`divergence`** records that gap for entries whose tests pin the divergent current behaviour.
- **`deferred`** marks a behaviour that is tracked but not yet covered by a test in this suite.
  The reason names the covering tests elsewhere in the repo, starts with "Not implemented in the
  SDK" for genuine feature gaps, or starts with "Not yet covered here" for tests that are planned.
- **`transports`** names the transports a behaviour applies to; omitted means transport-independent.
- **`issue`** carries the tracking link for a recorded gap once one is filed.

Tests link themselves to the manifest with a decorator:

```python
@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content() -> None: ...
```

`test_coverage.py` enforces the contract in both directions: every non-deferred requirement must
be exercised by at least one test, every deferred requirement by none, and an unknown ID fails at
import time. A behaviour without a manifest entry cannot be silently half-tested, and a manifest
entry without a test cannot be silently aspirational.

### The divergence lifecycle

1. A test reveals that the SDK does not do what the spec says. The test pins what the SDK
   *actually does* and a `Divergence(note=..., issue=...)` goes on the requirement.
2. When the behaviour is eventually fixed, the pinned test fails. Whoever makes the change finds
   the divergence note explaining that the old behaviour was a known gap, re-pins the test to the
   spec-correct output, and deletes the `Divergence`.
3. An empty divergence list means the SDK is spec-conformant on every behaviour the suite covers.

This is also the triage key for any rewrite: a test that fails on the new code path either has a
divergence note (the rewrite accidentally fixed a known gap — decide whether to keep the fix) or
it does not (the rewrite broke something that was correct — fix the rewrite).

### When a new spec revision is released

1. Update `SPEC_REVISION` and walk the new revision's changelog.
2. For each changed interaction, find its requirements (the IDs use the wire method strings the
   changelog speaks in), re-audit the tests against the new text, and update `source` links and
   assertions where behaviour legitimately changed.
3. New interactions get new requirements and new tests; removed interactions get their
   requirements deleted along with their tests.
4. A behaviour that is correct under both revisions needs no change beyond the `source` link.

## Writing a test

The shortest complete example of the conventions:

```python
@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content() -> None:
    """Arguments reach the tool handler; its content comes back as the call result."""

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "add"
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["a"] + params.arguments["b"]))])

    server = Server("adder", on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")]))
```

- **The server is defined inside the test** (or in a small fixture at the top of the file when
  several tests genuinely share it). The whole observable behaviour fits on one screen.
- **Test names are behaviour sentences** — they state the observable outcome, not the feature
  being poked. Docstrings add the one or two sentences of context a reviewer needs, including
  whether the assertion is spec-mandated, SDK-defined, or a known divergence.
- **Handlers assert their dispatch identity first** (`assert params.name == "add"`), proving the
  request that arrived is the request the test sent.
- **The result proves the round trip.** Server-side observations travel back to the test through
  the protocol itself (a tool returns what it saw) or through a closure-captured list; the test
  asserts after the call returns.
- **Order within a test**: server handlers → server construction → client callbacks → connect →
  act → assert. The test reads in the order the conversation happens.
- A registered handler or tool that a test never invokes gets a `raise NotImplementedError` body
  so it cannot silently become load-bearing.

### Choosing an assertion

| The property under test is… | Assert with |
|---|---|
| the result of a transformation (arguments → output, exception → error result) | `result == snapshot(...)` of the full object, so any field the implementation adds or drops fails the test |
| pass-through of an opaque value (`_meta`, cursors) | identity against the same variable that was sent — a snapshot of a pass-through value only matches the input because a human checked two literals correspond |
| an error | `pytest.raises(MCPError)` and a snapshot of `exc.value.error` when the message is the SDK's own; a plain `==` on `.code` against the `mcp.types` constant when it is not |
| third-party output embedded in a result (validation messages) | the stable prefix only — never pin text that changes with a dependency upgrade |

### Notifications and concurrency

The client's receive loop dispatches each incoming message to completion before reading the next,
and the in-memory transport delivers everything on one ordered stream. Together these guarantee
that every notification a server handler emits before its response reaches the client callback
before the originating request returns — so tests collect notifications into a plain list and
assert after the call, with no synchronisation. The exceptions:

- a notification not triggered by a request the test is awaiting needs an `anyio.Event` set in
  the receiving handler and awaited under `anyio.fail_after(5)`;
- the ordering guarantee does not survive transports that split messages across streams (the
  streamable HTTP standalone GET stream) — see `transports/test_streamable_http.py`.

### Coverage

CI requires 100% line and branch coverage, including `tests/`, and `strict-no-cover` fails the
build if a line marked `# pragma: no cover` is ever executed. When a new test starts covering a
pragma'd line in `src/`, delete the pragma in the same change. Do not add new `# pragma`,
`# type: ignore`, or `# noqa` comments; restructure instead.
