# Extensible transport API plan

Status: implementation in progress. New APIs still need final compatibility and native-binding review before release.

## Progress

| Work | Current evidence | Remaining |
| --- | --- | --- |
| Shared message contract | `mcp.shared.transport` exports stream, message, metadata, and transport types; existing client imports remain available | External adapter validation |
| Handler metadata | `TransportContext` reaches both handler APIs; concurrent principal-bound state, forged `_meta`, cross-peer replay, and missing-identity rejection are tested through the existing policy hook | Broker-specific identity-denial and cancellation scenarios |
| Multi-client lifecycle | Core tests cover shared lifespan, peer isolation, native readiness, and preservation of listener/startup failures across cleanup timeouts. `DirectDispatcher` now tracks operations on both peers and joins nested calls and handler cleanup; independent static review found no actionable issues | Final combined API and lifecycle review |
| Native dispatcher entry | Real gRPC binding uses protobuf envelopes with JSON payloads and no JSON-RPC frames. Maintained tests cover malformed traffic, capacity, cancellation, shutdown, error fidelity, subscriptions, and TLS. Both server APIs and multi-round trips also pass live examples on Python 3.10 and 3.14 | Final contract review, cross-platform validation, and the documented single-event-loop restriction |
| MQTT and AMQP adapters | Separate `examples/transports` package; both demos pass real two-peer calls for both server APIs and three client modes on Python 3.10 and 3.14; RabbitMQ cross-peer consumption is denied and borrowed channels survive cancellation | Full delivery/failure checks, MQTT provider limitations, record/replay, and adapter coverage |
| Release gates | Core: 6,027 tests pass with 100% branch coverage and `strict-no-cover`. Adapter package: 60 tests pass on Python 3.10 and 3.14. Every gRPC implementation and test file has 100% branch coverage on both interpreters. Ruff, both Pyright configurations, English docs, and all six HTTP conformance baseline legs pass | Whole adapter coverage remains 90%: AMQP is 31% and MQTT is 37%. Broker record/replay, remaining CI entries, and final API review remain |

`ServerRuntime` replaces the unshipped `ServerHost` name following naming review. It is not an MCP host or network listener. `DispatcherTransport` replaces the planned client factory: the explicit wrapper avoids duplicating the `Client` constructor's options or guessing what an arbitrary context manager yields. Existing `Transport` objects still yield stream pairs.

## Objective

You can implement MQTT, AMQP, or gRPC adapters outside the SDK and use them with `Client`, low-level `Server`, and `MCPServer`. Adapters use only supported public APIs. They reuse MCP negotiation, validation, middleware, callbacks, and result handling instead of implementing those features again.

There are two integration levels:

- **Message transport:** carries MCP JSON-RPC messages over another communication channel. MQTT, AMQP, and a gRPC bidirectional stream can use this level.
- **Native binding:** maps MCP operations to another RPC system, such as gRPC methods and protobuf messages. It uses the dispatcher boundary rather than pretending to be a JSON-RPC stream.

Supporting a native binding in the SDK does not make that binding an official MCP transport. Its wire format and interoperability claims need a separate specification review.

## Scope and constraints

- Preserve the existing `Transport` context manager and its stream-pair return value.
- Preserve `Client(...)`, `ClientSession(...)`, `Server.run(...)`, and built-in `MCPServer.run(...)` behavior.
- Add public entry points rather than removing or deprecating existing ones.
- Keep MQTT, AMQP, gRPC, and protobuf dependencies in adapter packages.
- Reuse `Dispatcher`, `JSONRPCDispatcher`, and the server runner functions.
- Do not introduce an interface with one method per MCP operation.
- Do not add a plugin registry, URL-scheme discovery, a universal broker configuration, or automatic request replay.
- Update relevant documentation with each public change. Do not add entries to the closed v1-to-v2 migration guide.

## Existing foundations

| Component | Existing extension point | Work needed |
| --- | --- | --- |
| `src/mcp/client/_transport.py` | Async context manager yielding `SessionMessage` streams | Document the full contract and expose supporting types through supported public imports |
| `src/mcp/client/client.py` | Accepts stream transports | Add an explicit lifecycle-managed dispatcher integration |
| `src/mcp/client/session.py` | Accepts `dispatcher=` | Preserve this entry point and make custom implementations supportable |
| `src/mcp/shared/dispatcher.py` | Request/notification boundary independent of wire encoding | Stabilize lifecycle, failures, ordering, and cancellation requirements |
| `src/mcp/server/runner.py` | Connection, stream, and single-request drivers | Expose hosting without requiring adapters to reconstruct the protocol pipeline |
| `src/mcp/server/lowlevel/server.py` | Runs one stream connection with its own lifespan | Support a host owning one lifespan across multiple peers |
| `src/mcp/server/mcpserver/server.py` | Built-in transport hosting | Make the same custom hosting surface available without private access |
| `src/mcp/shared/transport_context.py` | Transport-specific metadata | Connect it to actual user handler contexts |

## Recommended ownership model

| Layer | Owns |
| --- | --- |
| Adapter | Wire framing, physical connections, broker subscriptions, delivery settlement, routing, authenticated transport identity |
| Dispatcher | Request correlation, inbound scheduling, response delivery, notification ordering, progress and cancellation translation |
| MCP layer | Version negotiation, capability rules, typed validation, middleware, callbacks, result shaping |
| Server host | Application lifespan and supervision of active connections and requests |
| Application | Adapter configuration, authorization policy, and any operation-specific idempotency guarantees |

A broker connection is not an MCP client connection. Each logical peer needs isolated request correlation and, for handshake-era protocols, isolated negotiated state.

## Phase 1: Approve and pin the contracts

### Deliverables

- [ ] Inventory public imports, constructor forms, stream ownership, and observable failure behavior. Identify gaps in existing tests before adding more tests.
- [ ] Review real adapter call sites. Start with the [Google gRPC Python adapter](https://github.com/GoogleCloudPlatform/mcp-grpc-transport-py) and [Amazon MQ AMQP adapter](https://github.com/amazon-mq/mcp-amqp-transport). The latter is TypeScript and informs routing requirements, not Python API compatibility.
- [ ] Approve exact names and types for a shared transport import surface, an explicit client dispatcher factory, and a server hosting context. Names remain open until this review.
- [ ] Write complete client and server usage examples for both integration levels as design artifacts. Mark proposed calls as proposed until implemented.
- [ ] Define supported protocol versions and required features for each reference adapter. Start AMQP validation with AMQP 0.9.1 and MQTT validation with MQTT 5; do not imply support for other versions without testing them.
- [ ] Inspect the pinned conformance suite and map relevant existing scenarios to the work. SDK extension-point tests are separate from wire conformance tests.

### Conformance evidence

The pinned `@modelcontextprotocol/conformance@0.2.0-alpha.11` lists 69 frozen scenarios for 2026-07-28. Relevant shared-pipeline checks include `tools-call-with-progress`, `caching`, `request-metadata`, and the `input-required-result-*` scenarios. These existing features are reused, not reimplemented by the new extension points.

Fresh local baseline runs pass for all six legs. Server 2026-07-28 has 151 passing checks and server 2025-11-25 has 84. Client 2026-07-28 has 387 and client 2025-11-25 has 224. The default server leg has 204 passing checks and 25 expected failures; the default client leg has 464 passing checks and nine expected failures. The existing baselines were not changed, and no solo retry was needed. These runs use the HTTP harness and do not certify custom broker or protobuf wire bindings.

### Contract decisions

Specify readiness, single-entry/re-entry rules, borrowed versus owned resources, EOF, cancellation, shutdown order, and failure propagation. Preserve current behavior on existing entry points.

Distinguish malformed message observations, peer MCP errors, request timeouts, and terminal transport failures. A fatal receive or send failure must settle pending calls; yielding an exception item must not be mistaken for closing the channel.

Define which notification ordering the dispatcher guarantees, including the existing receive-order intercept used by subscriptions. Do not require globally ordered request completion.

Define how unsupported back-channels are reported. Transport capability never overrides a protocol-version prohibition.

For any newly implemented 2026-07-28 feature, require a matching conformance-suite test. If none exists, stop that feature and report the missing test so an issue can be raised upstream. Do not silently substitute a local test for the repository's conformance requirement.

### Exit condition

A maintainer approves the contract and compatibility matrix before implementation. No proposed native wire binding is presented as standardized without evidence.

## Phase 2: Expose shared types and transport metadata

Depends on phase 1.

### Shared transport deliverables

- [x] Make `Transport`, stream types, message types, and required adapter metadata available through documented public imports. Keep existing imports working.
- [x] Carry `TransportContext` from adapters through dispatch to the actual `ServerRequestContext` and high-level `MCPServer` context. Add fields or properties without replacing handler argument types.
- [x] Expose the transport context builder on supported stream-hosting paths instead of requiring adapters to construct the internal dispatcher recipe.
- [ ] Preserve existing HTTP request access, headers, SSE callbacks, and unanswered-request settlement behavior.
- [x] Define a supported way to bind verified transport identity to a request. Audit request-state principal binding and context propagation so custom authentication does not accidentally become anonymous.

### Shared transport acceptance checks

- A handler can observe typed adapter metadata without a fake Starlette request or a private import.
- Concurrent requests from different principals retain the correct identity and metadata, including during cancellation.
- Broker-supplied reply destinations are authorized against the caller rather than trusted as arbitrary routing instructions.
- Existing HTTP, stdio, request-state, and handler-context tests remain unchanged and pass.

## Phase 3: Add public multi-client server hosting

Depends on phase 2.

### Server runtime deliverables

- [x] Add a hosting context available from both `Server` and `MCPServer`. It owns one application lifespan and exposes serving operations bound to that lifespan state.
- [x] Support one logical stream connection through the existing dual-era runner. Each connection retains its own protocol and correlation state.
- [ ] Define supervision: one peer disconnecting or sending malformed traffic does not cancel unrelated peers; a fatal listener failure is reported to the host owner.
- [x] Stop admission before shutdown, cancel and join active work, close connection resources, and finally exit application lifespan. Document resource-cleanup deadlines separately from cooperative handler joins.
- [ ] Keep connection/session admission limits and queue bounds configurable at the layer that owns them. Do not create an unbounded task per broker message.
- [ ] Preserve the existing single-connection `Server.run()` behavior. Avoid migrating all built-in hosting paths in the same change.

### Server runtime acceptance checks

- Two clients can both issue request ID `1` without cross-delivery or shared negotiation state.
- Application lifespan enters once and exits once while multiple connections come and go.
- One client can disconnect while another completes a call.
- Startup failure, idle connections, in-flight cancellation, and shutdown release resources without hanging.
- A custom adapter can host an `MCPServer` without accessing `_lowlevel_server`.

## Phase 4: Validate message transports outside the SDK

Depends on phase 3. Develop MQTT and AMQP adapters independently once the shared contract is settled.

### Message transport deliverables

- [x] Build or adapt an external-package-shaped MQTT 5 client and server adapter using only public SDK imports.
- [x] Build or adapt an AMQP 0.9.1 client and server adapter using only public SDK imports.
- [ ] Run the same client/server behavior checks through each adapter. Neither adapter may bypass the runner by calling tool methods directly.
- [ ] Document the wire binding, configuration, supported features, limits, failure behavior, and backend requirements for each adapter.

### MQTT binding decisions

Specify request and reply topics, subscription readiness, peer/session identity, and reply-topic authorization. Define QoS and duplicate handling. Do not retain command messages; define rejection of unexpected retained deliveries. Specify message expiry, disconnect detection, and reconnect behavior.

### AMQP binding decisions

Specify exchanges, queues, reply addresses, consumer prefetch, and publisher confirmation behavior. Define acknowledgment timing relative to request execution and response publication. Specify redelivery, poison-message handling, and expiry. Keep handshake-era traffic on the appropriate logical peer/worker; do not load-balance it blindly across independent sessions.

### Delivery guarantees

Broker delivery guarantees are not exactly-once tool execution. Document the crash window between a side effect, response publication, and message settlement. Do not retry arbitrary operations automatically. If deduplication is offered, define identity scope, retention, and behavior after process restart.

Cancellation must reach the worker running the request. Reconnect must either restore explicitly supported state or fail the old calls and create a fresh logical connection. It must not silently replay calls.

### Message transport acceptance checks

Test a real broker for both adapters: multiple clients, out-of-order responses, duplicate delivery, disconnect/reconnect, backpressure, stale deliveries, and authenticated routing. Record supported external interactions and review recordings for secrets. Do not claim real broker behavior from handwritten mocks.

Passing this phase establishes the JSON-RPC transport milestone. It does not complete native gRPC support.

## Phase 5: Support native dispatcher integrations

Depends on phases 1-3. This work can proceed alongside phase 4, but the final contract must incorporate findings from both paths.

### Native dispatcher deliverables

- [ ] Stabilize the custom `Dispatcher` lifecycle after reviewing the existing JSON-RPC and direct implementations and a native gRPC prototype.
- [x] Add an explicit `DispatcherTransport` wrapper accepting an async context manager yielding a dispatcher. Reuse existing client negotiation, caching, extensions, callback, and cleanup paths. Do not infer the integration type from an ambiguous context-manager return value.
- [x] Let the server runtime serve a dispatcher through the existing runner pipeline. Native requests retain inbound envelope/version validation at the untrusted entry boundary.
- [ ] Define native mappings for deadlines, transport cancellation, MCP errors, progress, notifications, request IDs, and subscriptions. Reuse existing call options; do not make HTTP-only options mandatory for native implementations.
- [x] Support required notification-intercept behavior and explicit request IDs used by subscriptions. Live regression tests cover acknowledgment/event routing, collisions, minted IDs, and ID reuse.
- [x] Verify arbitrary MCP method names and extension payloads survive the boundary. The gRPC binding carries arbitrary method names and preserves JSON integer precision; recorded calls also cover error codes outside int32.
- [ ] Preserve stream exception observations on the existing client paths. Define equivalent diagnostics for native transports without requiring `isinstance(JSONRPCDispatcher)` in third-party code.

### Native dispatcher acceptance checks

- The same high-level `Client` operations work through stream and native dispatcher integrations.
- Negotiation, multi-round-trip results, middleware, and result validation run through shared MCP code.
- Native cancellation and disconnects settle calls without requiring a fabricated JSON-RPC connection.
- MCP errors retain code, message, and data according to the approved mapping; gRPC status failures remain distinguishable where needed.
- The adapter has no duplicate client-session API and does not subclass `ClientSession` to reimplement every MCP method.

## Phase 6: Validate native gRPC and publish the contract

Depends on phases 4 and 5.

### Native binding validation deliverables

- [x] Implement a native gRPC client and server reference adapter with a documented protobuf-envelope binding. This is a reference binding, not interoperability with another project's schema.
- [x] Test notification/progress delivery, deadlines, cancellation, metadata, extension payloads, and error fidelity over a real gRPC connection. Replay checks are supplemented by tests executing the current server.
- [x] Document asyncio-only requirements for `grpc.aio`, including the single-loop restriction. Core extension points remain AnyIO-compatible; native adapters do not claim Trio support.
- [x] Validate both low-level `Server` and high-level `MCPServer` hosting, including concurrent peers and independent request delivery.
- [ ] Document stable import paths and complete runnable examples in the relevant existing pages: `docs/client/transports.md`, `docs/advanced/low-level-server.md`, `docs/run/index.md`, `docs/run/asgi.md`, and `docs/handlers/context.md`. Update lifespan, authorization, and client caching pages where their contracts are affected.
- [ ] Obtain fresh API-compatibility and adversarial lifecycle/security reviews. Reviewers should specifically challenge identity isolation, replay, callback deadlocks, and incomplete cleanup.

### Native binding validation exit condition

MQTT, AMQP, and native gRPC adapters work on both sides without private imports, duplicated MCP semantics, or new runtime dependencies in the core SDK. Compatibility and validation gates below pass.

## Validation gates for every implementation slice

Prefer existing public-API tests and add only missing behavior checks. Core lifecycle tests use in-memory execution, events, and bounded waits. Real transport semantics use real services. Keep test files aligned with the source tree and follow `.claude/skills/test-quality/SKILL.md`.

Cover the following combinations where applicable:

| Dimension | Cases |
| --- | --- |
| Server API | `Server`, `MCPServer` |
| Client integration | Existing stream transport, new dispatcher factory |
| Protocol | Legacy handshake, automatic discovery, pinned modern version |
| Messaging | Concurrent requests, peer errors, notifications, progress, subscriptions, extension methods |
| Lifecycle | Startup failure, timeout, peer cancellation, EOF, send failure, shutdown |
| Isolation | Repeated request IDs across peers, independent negotiated state, distinct identities |
| Delivery | Backpressure, duplicate and late messages, worker failure, reconnect |

Transport bindings must document unsupported combinations rather than silently pass partial behavior as full support.

Run repository checks with the frozen lockfile:

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
./scripts/test
```

Require 100% branch coverage and `strict-no-cover` for SDK changes. Run the existing client/server conformance jobs for both protocol eras and the default suite. These protect current wire behavior; they do not by themselves certify an MQTT, AMQP, or native protobuf binding. Validate cross-version and platform behavior in the repository CI matrix.

## Review findings addressed

A focused independent reviewer found two native lifecycle defects: cancellation was signalled only after handler cleanup, and a five-second join could abandon handlers before application lifespan closed. The server now signals cancellation before unwinding a handler task group. Both client and server join active work without abandoning it at a deadline. Live checks hold shielded cleanup beyond five seconds and prove that resources remain alive until it finishes. Shutdown can wait indefinitely for code that ignores cancellation; a process supervisor owns any hard termination deadline.

Follow-up review confirmed those corrections and found a borrowed-channel closure race. It was reproduced through `Client.list_tools()` immediately after `channel.close()`, then corrected by consulting native channel state before constructing an RPC. The regression passes without making a network request.

The `reviewer` Agent Hub profile is available. Earlier attempts used nonexistent profile names; subsequent focused reviews completed. Final review of the complete API and adapter work is still required.

## Latest validation slice

The four standalone gRPC shutdown programs are maintained AnyIO regressions under `examples/transports/tests/`. The tests execute real loopback servers and hold shielded cleanup beyond the former five-second join deadline. Additional cases exercise malformed frames, saturation, application and validation errors, callback isolation, request-ID collisions, and subscription routing. Cassette tests compare their recorded native results against the current in-process MCP handler, so replay does not leave their server handlers untested.

`DirectDispatcher` previously returned from `run()` while a caller task was still unwinding a request or notification handler. Operations now register a cancellation scope and completion event on both peers. Closing either peer cancels them; `run()` joins completion before returning. Tests cover both closing peers, requests and notifications, nested back-channel calls, ordinary handler errors, and in-process client lifespan ordering. The dispatcher/client subset also passes all 108 tests on Python 3.10.

The native adapter now exposes gRPC's verified `peer_identity_key` and immutable `peer_identities`. A fresh adversarial review found no direct spoofing path but requested stronger boundary assertions and authority documentation. Five live cases now cover plaintext, server-only TLS, mutual TLS, absent client certificates, and certificates signed by an untrusted key with the same issuer name. Middleware proves rejected peers never reach MCP dispatch. Accepted requests prove neither MCP client-info claims nor forged invocation metadata can supply or replace certificate identity. Empty identity does not prove plaintext, and names are not globally unique across independent trusted authorities. A fresh read-only closeout review found no remaining correctness, security, or test gaps in this TLS slice; it did not approve the combined API.

TLS validation exposed a gRPC completion-queue limitation, reproduced without MCP in `examples/transports/reproduce_grpc_loop_shutdown.py`. With `grpcio==1.84.0` on macOS/Python 3.14.6, cancelled connectivity watches can complete after `channel.close()` and target a previously closed event loop. The adapter suite keeps one AnyIO runner for its session, while still closing per-test resources. The README records this support restriction, not an upstream fix; repeated loop lifetimes and final native-queue drainage are not certified.

Current evidence is in `/tmp/mcp-core-final.log`, `/tmp/mcp-adapter-final310.log`, `/tmp/mcp-adapter-final314.log`, `/tmp/mcp-docs-final.log`, and `/tmp/mcp-conformance-final-{client,server}-*.log`. Coverage data uses `/tmp/mcp-adapter-final310` and `/tmp/mcp-adapter-final314`. Core coverage is 100%; total adapter coverage is 90%, with only MQTT/AMQP implementation gaps remaining. Generated protobuf implementation is excluded as compiler output, not handwritten adapter code.

## Next implementation work

1. Settle broker record/replay. `cassetter` has no MQTT/AMQP interceptor. Its gRPC wrapper also omits parts of streaming cancellation and matches only RPC methods; current tests supplement matching with serialized-request assertions and keep each cassette to one RPC. Do not substitute handwritten broker mocks to clear coverage.
2. Exercise broker redelivery, expiry, connection loss, malformed frames, cancellation, saturation, and TLS identity denial. Resolve aiomqtt's queue-overflow drops and discarded negative publish reason codes, or choose a provider with the required failure signals. Bound executing broker work, not only queued messages and connections.
3. Complete remaining CI matrix coverage and external adapter compatibility checks. Existing HTTP conformance baselines and local native coverage do not certify broker delivery semantics or another protobuf binding.
4. Obtain final independent compatibility and lifecycle/security reviews of the combined API and adapters. The scoped DirectDispatcher and TLS reviews are not approval of the entire change. Keep the contract provisional until those gates and maintainer approval are complete.

The local Mosquitto and RabbitMQ fixtures are pinned by image digest. The temporary `mcp-sdk-transport-check` containers and network were removed after verification. Their public test credentials and ACLs are in `examples/transports/brokers/`; they are not production configuration.

## Delivery order

1. Approve the contract, compatibility matrix, and usage examples.
2. Expose shared types and context propagation in small reviewable changes.
3. Add server hosting with lifecycle and isolation tests.
4. Validate MQTT and AMQP adapters while implementing dispatcher integration.
5. Complete native gRPC validation and review the combined public contract.

Each implementation change includes its tests and affected documentation. Do not defer coverage or lifecycle verification to the last phase. Do not publish the contract as stable until both message-based and native integrations have exercised it.
