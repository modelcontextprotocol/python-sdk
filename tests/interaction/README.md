# Interaction-model test suite

This suite enumerates the MCP interaction model as end-to-end tests: one test per piece of
functionality, asserting the full client↔server round trip through the public API. It exists to
pin the SDK's observable behaviour — every request type, every notification direction, every
error plane — so that internal rewrites of the send/receive path can be proven equivalent by
running the suite before and after.

```bash
uv run --frozen pytest tests/interaction/
```

The whole suite is in-process and event-driven — including the streamable HTTP, SSE, and OAuth
flows — with a single subprocess test for stdio.

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
  the constants in `mcp_types`; error *message strings* are pinned only where they are the
  SDK's own deliberate output.
- **No sleeps, no real I/O.** Concurrency is coordinated with `anyio.Event`; every wait that
  could hang is bounded by `anyio.fail_after(5)`. The HTTP and OAuth tests drive the Starlette
  app in-process through the suite's streaming ASGI bridge (`transports/_bridge.py`), which
  delivers each response chunk as the server produces it — full duplex, but still no sockets,
  threads, or subprocesses anywhere outside the one stdio test.

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
  transports/           behaviour specific to one transport (sessions, resumability, framing)
  auth/                 OAuth flows against an in-process authorization server
```

The two server APIs produce genuinely different wire output for the same conceptual feature
(`MCPServer` generates schemas, converts exceptions to `isError` results, attaches structured
content), so they get parallel directories with mirrored file names rather than one parametrized
test body — each directory pins its flavour's true output exactly.

### The transport matrix

Transport-agnostic tests take the `connect` fixture instead of constructing `Client(server)`
directly, and therefore run once per transport: over the in-memory transport, over the server's
real streamable HTTP app driven in-process through the streaming bridge (in both stateful and
stateless configurations), and over the legacy SSE transport the same way. A test connects with
`async with connect(server, ...) as client:` and asserts the same output on every leg, because the
transport is not supposed to change observable behaviour. Requirements that need a server-to-client
back-channel or persisted session state are carved out of the stateless arm via `arm_exclusions`.
Tests that are tied to one transport do not use the fixture: the wire-recording tests
(their seam is the in-memory stream pair), the bare-`ClientSession` lifecycle tests, the
real-clock timeout tests (the timeout machinery is transport-independent and must not race
transport latency), and everything under `transports/`, which pins behaviour only observable on
that transport.

A transport conformance test in `transports/` speaks raw `httpx2` against the mounted ASGI app
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
- **`deferred`** marks a behaviour that is tracked but has no test in this suite, with a precise
  reason: the SDK does not implement it, the negative cannot be observed, the assertion is
  schema-level rather than interaction-level, the feature is experimental (tasks), or the test
  would require real-time waits the suite refuses.
- **`transports`** names the transports a behaviour applies to; omitted means transport-independent.
- **`issue`** carries the tracking link for a recorded gap once one is filed.
- **`note`** carries free-form context that does not fit `divergence` or `deferred`.
- **`added_in`** / **`removed_in`** bound the spec versions the behaviour exists in, as a half-open
  `[added_in, removed_in)` window.
- **`supersedes`** / **`superseded_by`** link a retired entry to its replacement; the link is
  bidirectional and both ends must be versioned.
- **`arm_exclusions`** carve specific `(transport, spec_version)` matrix cells out with a typed
  `ArmExclusionReason`.
- **`known_failures`** mark specific `(transport, spec_version)` cells as strict xfail.

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

A requirement may carry both `divergence` and `deferred`: the divergence records that the SDK falls
short of the spec, and the deferral records why no test pins it (typically because the divergent
behaviour cannot be driven through the public API). Divergence alone implies a test pins the
divergent behaviour; divergence plus deferred means the gap is known but unpinned.

This is also the triage key for any rewrite: a test that fails on the new code path either has a
divergence note (the rewrite accidentally fixed a known gap — decide whether to keep the fix) or
it does not (the rewrite broke something that was correct — fix the rewrite).

### Spec versions and the era axis

`SPEC_VERSIONS` in `_requirements.py` is the ordered tuple of protocol revisions the suite
exercises. `SPEC_BASE_URL` (and `SPEC_2026_BASE_URL`) are pinned literals — not derived from
`SPEC_VERSIONS` — so growing the active axis never repoints existing `source` links. The
`connect` fixture fans out over `CONNECTABLE_TRANSPORTS × SPEC_VERSIONS`, but the grid is
filtered per test:
`pytest_generate_tests` reads the test's stacked `@requirement` marks and calls `compute_cells()`,
which intersects the admissible cells across every cited requirement — a cell survives only if
**all** of the test's requirements admit it.

`streamable-http-stateless` is the fourth connectable transport: the 2025-era unofficial stateless
mode where each request opens a fresh transport, no session id is issued, and there is no standalone
GET stream. Requirements that need a server→client back-channel or persisted session state are
excluded from that arm via `arm_exclusions` (reasons `server-initiated-request` and
`requires-session`).

What admits or excludes a cell:

- **`added_in` / `removed_in`** gate which spec versions a requirement exists in, as a half-open
  `[added_in, removed_in)` window. A test runs only on versions inside every cited requirement's
  window.
- **`arm_exclusions`** carve specific `(transport, spec_version)` cells out with a typed
  `ArmExclusionReason`. The reason vocabulary doubles as a re-admission checklist: when the gap
  closes, grep for the reason string to find every cell to re-admit.
- **`known_failures`** keep a cell in the grid but mark it as a strict xfail — the test runs and
  must fail; an unexpected pass fails the suite.
- **`TRANSPORT_SPEC_VERSIONS`** era-locks a transport to a subset of spec versions (currently only
  `sse` is locked to `2025-11-25`). A `(transport, version)` cell is dropped if the version is not
  in the transport's entry; transports absent from the map serve every spec version. This is the
  mechanism for cutting an entire transport off from a new revision (or admitting it).
- **`transports`** is descriptive metadata for the non-`connect` transport-specific suites under
  `transports/` and does **not** drive cell generation. Only `arm_exclusions`, `added_in`,
  `removed_in`, and `TRANSPORT_SPEC_VERSIONS` filter the grid.
- **`supersedes` / `superseded_by`** link a retired entry to its replacement. `test_coverage.py`
  enforces that links are bidirectional and versioned: the retired entry carries `removed_in`, the
  replacement carries `added_in`.

Node IDs stay `[transport]` while `len(SPEC_VERSIONS) == 1`, so today's test IDs are
byte-identical to before the era axis existed. They become `[transport-version]` the moment a
second version is appended to `SPEC_VERSIONS`.

When a new spec revision lands:

1. Append the version string to `SPEC_VERSIONS` (and to the `SpecVersion` `Literal`).
2. Walk the new revision's changelog.
3. For each affected requirement: set `removed_in` on retired behaviour, add a new entry with
   `added_in` for its replacement, and link the pair with `supersedes` / `superseded_by`.
   Behaviour that survives unchanged needs nothing beyond a re-audit of its `source` URL.
4. For requirements that cannot run on the new era's path, add an `arm_exclusions` entry with the
   appropriate `ArmExclusionReason`.
5. Review `TRANSPORT_SPEC_VERSIONS`: any era-locked transport will not produce cells on the new
   version unless its entry is extended (or removed); add an entry for any transport the new
   revision retires.

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
- A test that needs a peer no real `Server` or `Client` can play (a server that answers initialize
  with an unsupported version, a client that sends malformed params) plays that side of the wire by
  hand over `create_client_server_memory_streams()`. This scripted-peer pattern is the suite's only
  way to drive behaviour the typed API cannot produce, and the docstring of every such test says so.

Stack a second `@requirement` decorator only when a test's natural assertions incidentally prove
another behaviour — one capabilities snapshot proving four `*:capability:declared` entries, one
input-schema identity check proving each preserved keyword. Do not build a test around covering
many requirements at once; if the assertions would be separate, write separate tests.

### Choosing an assertion

| The property under test is… | Assert with |
|---|---|
| the result of a transformation (arguments → output, exception → error result) | `result == snapshot(...)` of the full object, so any field the implementation adds or drops fails the test |
| pass-through of an opaque value (`_meta`, cursors) | identity against the same variable that was sent — a snapshot of a pass-through value only matches the input because a human checked two literals correspond |
| an error | `pytest.raises(MCPError)` and a snapshot of `exc.value.error` when the message is the SDK's own; a plain `==` on `.code` against the `mcp_types` constant when it is not |
| third-party output embedded in a result (validation messages) | the stable prefix only — never pin text that changes with a dependency upgrade |

### Notifications and concurrency

The client's dispatcher starts a task per incoming notification in arrival order but does not
await it before reading the next message, so completion order is not structural. What still
holds: the in-memory transport delivers everything on one ordered stream, and a callback that
records synchronously (no `await` before the append) finishes its scheduling slice before the
awaited request's waiter — woken strictly later — resumes. So tests whose callbacks are plain
appends may still collect into a list and assert after the call. A callback that awaits before
recording loses that ordering and must synchronise. The other exceptions:

- a notification not triggered by a request the test is awaiting needs an `anyio.Event` set in
  the receiving handler and awaited under `anyio.fail_after(5)`;
- the ordering guarantee does not survive transports that split messages across streams (the
  streamable HTTP standalone GET stream) — see `transports/test_streamable_http.py`.

### Coverage

CI requires 100% line and branch coverage, including `tests/`, and `strict-no-cover` fails the
build if a line marked `# pragma: no cover` is ever executed. When a new test starts covering a
pragma'd line in `src/`, delete the pragma in the same change. Do not add new `# type: ignore` or
`# noqa` comments; restructure instead. Two pragmas are sanctioned in this suite's test code, both
for known-upstream tracer bugs and only after restructuring has been tried: `# pragma: no branch`
on a `with`/`async with` line whose only fault is coverage.py mis-tracing the exit arc of a nested
async context (reserve it for shapes that cannot collapse — a sync `with` adjacent to an
`async with`); and `# pragma: lax no cover` on a single statement that 3.11's tracer drops because
the preceding `async with` unwinds via `coro.throw()` (python/cpython#106749, wontfix on 3.11) —
this hits any test that must run statements after a `ClientSession`/`streamable_http_client` exits
but still inside an outer `async with`, and no restructure can avoid it.

A handful of `# pragma: lax no cover` markers in `src/` cover teardown exception handlers whose
execution is timing-dependent under the in-process HTTP bridge — the POST-stream and
stateless-session `except Exception` handlers in `server/streamable_http*.py` and the
`_terminated` check in `message_router`. `strict-no-cover` does not check `lax` lines; do not
promote them to strict `no cover` without first making the teardown ordering deterministic. The
suite also relies on a one-line `src/mcp/server/sse.py` fix (`sse_stream_reader.aclose()`) that
closes a stream the SSE leg would otherwise leak.
