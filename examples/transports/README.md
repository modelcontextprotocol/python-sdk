# Reference custom transports

This package contains experimental adapters for the public MCP transport API. Installing `mcp` does not install their dependencies. The adapters are not production-ready transports or official MCP wire bindings.

## Native gRPC

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv sync --frozen --package mcp-transport-examples --group dev
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_grpc.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_grpc_features.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples --group dev pytest -c examples/transports/pyproject.toml examples/transports/tests --record-mode=none
uv run --frozen pyright --project examples/transports
```

Run these commands from the repository root. The programs start their own loopback gRPC listener. No broker is needed. `grpc_client(channel)` and `grpc_server(listener)` return `DispatcherTransport` objects for the existing client and server runtime APIs. You own the channel and listener; runtime shutdown stops MCP handlers without taking ownership of other gRPC services on the listener.

Register the binding through `runtime.connect(grpc_server(listener))` before starting the listener. Use one MCP binding per gRPC server. The server adapter rejects excess work at `max_requests`, which defaults to 64, rather than queuing unlimited waiting handlers.

The binding serves modern per-request MCP envelopes. It has no legacy initialize handshake. Each MCP request is a native server-streaming RPC on `/mcp.transport.example.MCP/Call`; gRPC correlates calls and provides deadlines and cancellation. The auxiliary request ID supports MCP subscription correlation and stays local to each client's calls. Native progress uses the protobuf `report_progress` opt-in from `CallOptions["on_progress"]`; `_meta.progressToken` alone does not enable it. Progress carries the auxiliary ID for notification observers, while the originating RPC selects the callback without token-based demultiplexing.

`mcp_transport_examples/rpc.proto` defines protobuf envelopes with JSON-encoded parameters, results, and error data. There is no JSON-RPC envelope. JSON payloads preserve arbitrary extension fields and integer precision, which protobuf `Struct` would otherwise lose through its floating-point number representation. This is an example binding, not compatibility with another project's gRPC schema.

Notifications precede one terminal result or error, followed by end-of-stream. Progress, subscription acknowledgments, and change events use the originating RPC's response stream. Unsolicited notifications without a request channel are unsupported. Ordinary MCP errors preserve their code, message, and data. Native deadline failures become `REQUEST_TIMEOUT`; other gRPC failures become `CONNECTION_CLOSED` with the original status exception as their cause.

The examples and regression tests check both server APIs, progress, subscriptions, multi-round-trip results, concurrent clients with colliding request IDs, caller cancellation, deadlines, runtime shutdown, borrowed-channel closure, and client shutdown during a blocked callback. Cancellation is signalled before handler cleanup begins. Active handlers and callbacks are joined before their owning resources close, including shielded cleanup that takes longer than five seconds. Code that ignores cancellation indefinitely can therefore hold shutdown indefinitely; enforce a hard process deadline in your supervisor rather than closing resources under running code. The SDK's five-second transport and application cleanup deadlines do not replace this join.

### Generate the protobuf bindings

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples --group dev python -m grpc_tools.protoc --proto_path=examples/transports --python_out=examples/transports --pyi_out=examples/transports examples/transports/mcp_transport_examples/rpc.proto
```

Use the pinned compiler. Generated implementation code is excluded from adapter coverage; regeneration checks its provenance.

### TLS and peer identity

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples --group dev pytest -c examples/transports/pyproject.toml examples/transports/tests/test_grpc_tls.py --record-mode=none
```

These tests create temporary certificate authorities and real local TLS endpoints. They check mutual TLS, server-only TLS, and plaintext connections. Missing or untrusted client certificates cannot reach MCP middleware when the listener requires client authentication. Forged MCP client information and gRPC invocation metadata do not change the verified identity.

Configure TLS through your gRPC channel and listener credentials. Set `require_client_auth=True` on `grpc.ssl_server_credentials()` when clients must present a certificate. Handlers receive `GRPCContext.peer_identity_key` and `peer_identities` from gRPC's native authentication context. Without client authentication, these are `None` and an empty tuple, including on encrypted server-only TLS connections.

Certificate validation is not application authorization. The identity values do not identify their issuing authority. If you trust independent authorities that can issue the same common name or subject alternative name, do not treat that name as a globally unique principal. Choose a trust-domain namespace and certificate-issuance policy before using these values with `RequestStateSecurity.bind_principal`. An issuer-name string or untrusted invocation metadata cannot supply that trust boundary.

### Event-loop lifetime

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/reproduce_grpc_loop_shutdown.py
```

This diagnostic intentionally fails when a native completion targets a closed loop. It reproduces the limitation without importing MCP. The failure was observed with `grpcio==1.84.0` on macOS and Python 3.14.6; the assertion includes the runtime versions.

Keep one long-lived asyncio event loop per process or test worker. Create, use, and close all gRPC resources on that loop. Repeated `anyio.run()` or `asyncio.run()` lifetimes are outside this adapter's current support. gRPC's process-wide completion queue can deliver cancelled connectivity-watch callbacks after `channel.close()` returns. Joining MCP handlers does not drain those native callbacks. The adapter tests keep one AnyIO runner alive for the session; they do not suppress loop errors or claim an upstream correction.

### Validation boundaries

The dedicated CI job runs the adapter suite on Python 3.10 and 3.14 and retains JUnit results. Final compatibility review and cross-platform validation remain open gates.

The gRPC cassette tests record real calls with `cassetter` and replay with `--record-mode=none`. They check payload fidelity, progress, and application errors. They also compare serialized requests with the recording: the current matcher matches only the RPC method, which is insufficient for a generic MCP binding. Each cassette contains one RPC to avoid replaying a newly recorded call as the response to a different request during recording.

The lifecycle, capacity, and malformed-frame regression tests own a gRPC server inside the test process. That server is the software under test, not an external service; replaying its outputs would bypass the behavior being checked. Cassette tests separately compare recorded native results with the current in-process MCP handler. `cassetter` lacks parts of the streaming-call cancellation interface, so it is not used to stand in for live lifecycle checks.

Binary protobuf payloads are not pattern-scrubbed. Inspect new cassettes before committing them; the checked-in recordings contain only public test data.

## MQTT 5

```bash
docker compose -p mcp-sdk-transport-check -f examples/transports/compose.yaml up --wait
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv sync --frozen --package mcp-transport-examples --group dev
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_mqtt.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_mqtt_disconnect.py
docker compose -p mcp-sdk-transport-check -f examples/transports/compose.yaml down --volumes
```

The programs check concurrent calls for two peers, both server APIs, and `legacy`, `auto`, and pinned `2026-07-28` clients. The disconnect check uses a broker-forced session takeover and requires a pending call to receive `CONNECTION_CLOSED` without relying on its request timeout. CI runs these live checks separately from cassette replay.

`demo_mqtt.py` contains complete connection setup. You own and enter the MQTT client before entering `mqtt_transport()`. The adapter unsubscribes on exit but does not close the borrowed client. Each logical peer gets a dedicated client and messages iterator; session identifiers are agreed out of band. Discovery and multiplexing are not implemented.

### MQTT wire binding

| Property | Value |
| --- | --- |
| Requests | `mcp/<principal>/<session>/requests` |
| Replies | `mcp/<principal>/<session>/responses` |
| Framing | One JSON-RPC message per publish |
| Delivery | QoS 2 only |
| Close | Empty payload |
| Retention | Never retain commands; reject retained deliveries |
| Expiry | MQTT message expiry, default 60 seconds |
| Message limit | 4 MiB by default |
| Reconnect | Fail old calls and establish fresh topics; never replay requests |

Configure a QoS-2, non-retained Last Will with an empty payload on the outgoing topic before CONNECT. The broker publishes it on unexpected disconnection; the example uses a 15-second keepalive to bound detection of a silent network loss. An already-connected client cannot acquire a Last Will through this adapter. Use a client request timeout for startup failures before the peer subscribes: a non-retained will is not replayed to a later subscriber.

QoS 2 handles protocol retransmissions within a session, not exactly-once tool execution. Republishing a request can repeat its side effects. Malformed messages become recoverable stream exceptions; connection loss ends the read stream.

### MQTT authorization and limits

The local fixture uses per-user topic ACLs and `use_username_as_clientid true`, so another authenticated user cannot evict a peer by claiming its client ID. It supports one connection per credential; server routes use separate `server-alice` and `server-bob` users. Deployments needing multiple sessions per credential need broker authorization of client-ID namespaces instead.

The fixture uses public test credentials, binds only to localhost, and disables persistence. Do not deploy it. Use TLS and your broker's authorization policy in production, and bind request state to a verified, authority-qualified principal through `RequestStateSecurity.bind_principal`. A successful SUBACK is not proof that Mosquitto's ACL permits message delivery.

The example bounds aiomqtt's incoming queue at 256 messages, but aiomqtt can drop messages when it fills. Its public publish callback also discards negative broker reason codes. These are unresolved reliability blockers, not successful execution acknowledgments. Request timeouts and monitoring are required; neither the queue bound nor MQTT QoS bounds concurrently executing tool handlers.

`cassetter` has no MQTT interceptor. Full broker branch coverage, saturation and failure validation, and production TLS authorization remain open gates. The provider uses asyncio and requires a selector event loop on Windows; Trio and Windows support have not been validated. Change the local port with `MQTT_TEST_PORT` (default 13883).

## AMQP 0.9.1

```bash
docker compose -p mcp-sdk-transport-check -f examples/transports/compose.yaml up --wait
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv sync --frozen --package mcp-transport-examples --group dev
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_amqp.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_amqp_permissions.py
docker compose -p mcp-sdk-transport-check -f examples/transports/compose.yaml down --volumes
```

The programs reuse the same two-peer application checks as MQTT for both server APIs and all three client modes. The permission check requires RabbitMQ to reject publication through the default exchange and another principal's exchange. CI runs both programs against the pinned RabbitMQ fixture.

`demo_amqp.py` contains complete setup. You own the connection and publisher-confirm channel, and enter them before `amqp_transport()`. The adapter cancels its consumer without closing that borrowed channel. Use a fresh queue pair for each logical connection and do not load-balance handshake-era traffic across independent sessions.

### AMQP wire binding

| Property | Value |
| --- | --- |
| Requests | `mcp.<principal>.<session>.requests` |
| Replies | `mcp.<principal>.<session>.responses` |
| Routing | One direct exchange named `<queue>.exchange` per receiving queue |
| Framing | One JSON-RPC message per delivery; `application/json` content type |
| Delivery | Publisher confirmations; acknowledge before SDK handoff |
| Close | Empty JSON-typed message body |
| Retention | Nondurable, auto-delete queues |
| Expiry | Message TTL and unused queue expiry, default 60 seconds |
| Message limit | 4 MiB by default |
| Redelivery | Reject without requeue; never replay requests automatically |

Acknowledging before SDK handoff avoids automatically rerunning uncertain work, but a process failure in that window can lose it. Publisher confirmations describe broker delivery, not tool completion or exactly-once execution. Applications still own idempotency.

Queues hold at most 256 ready messages and reject publication on overflow. Consumer prefetch bounds unacknowledged deliveries, not concurrently executing tool handlers. Malformed messages become recoverable stream exceptions; channel closure ends the read stream.

### AMQP authorization and limits

The fixture grants each client publication rights only to its request exchanges. Queue-name permissions alone do not constrain default-exchange routing, so client credentials cannot publish through `amq.default`. The live permission check also rejects writes to another principal's exchange. Server credentials manage both sides of the configured routes; messages cannot choose an arbitrary reply destination.

The fixture uses public test credentials, listens only on localhost, and disables durable storage. Do not deploy it. Use TLS and broker authorization in production, and bind request state to verified, authority-qualified identity. Change the local port with `AMQP_TEST_PORT` (default 15672).

`cassetter` has no AMQP interceptor. Full broker branch coverage, broader delivery/failure validation, and production TLS checks remain open gates. The provider uses asyncio; Trio and Windows validation have not been completed.
