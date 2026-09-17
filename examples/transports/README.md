# Reference custom transports

```bash
docker compose -p mcp-sdk-transport-check -f examples/transports/compose.yaml up --wait
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv sync --frozen --package mcp-transport-examples --group dev
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_mqtt.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_amqp.py
docker compose -p mcp-sdk-transport-check -f examples/transports/compose.yaml down --volumes
```

Run these commands from the repository root. Both programs exit successfully only after checking concurrent calls for two peers, both `Server` and `MCPServer`, and `legacy`, `auto`, and pinned `2026-07-28` clients. The server lifespan starts once per run, not once per peer.

The adapters import only public SDK APIs. They live in a separate workspace package so installing `mcp` does not install MQTT or AMQP dependencies. They are reference implementations under development, not production-ready transports or official MCP wire bindings. The native gRPC binding is described below.

## Native gRPC

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_grpc.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples python examples/transports/demo_grpc_features.py
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples --group dev pytest -c examples/transports/pyproject.toml examples/transports/tests/test_grpc*.py --record-mode=none
```

These programs start their own loopback gRPC listener. No broker is needed. `grpc_client(channel)` and `grpc_server(listener)` return `DispatcherTransport` objects for the existing client and server runtime APIs. You own the channel and listener; runtime shutdown stops MCP handlers without taking ownership of other gRPC services on the listener.

Register the binding through `runtime.connect(grpc_server(listener))` before starting the listener. Use one MCP binding per gRPC server. The server adapter rejects excess work at `max_requests`, which defaults to 64, rather than queuing unlimited waiting handlers.

The binding serves modern per-request MCP envelopes. It has no legacy initialize handshake. Each MCP request is a native server-streaming RPC on `/mcp.transport.example.MCP/Call`; gRPC correlates calls and provides deadlines and cancellation. The auxiliary request ID supports MCP subscription correlation and stays local to each client's calls.

`mcp_transport_examples/rpc.proto` defines protobuf envelopes with JSON-encoded parameters, results, and error data. There is no JSON-RPC envelope. JSON payloads preserve arbitrary extension fields and integer precision, which protobuf `Struct` would otherwise lose through its floating-point number representation. This is an example binding, not compatibility with another project's gRPC schema.

Notifications precede one terminal result or error, followed by end-of-stream. Progress, subscription acknowledgments, and change events use the originating RPC's response stream. Unsolicited notifications without a request channel are unsupported. Ordinary MCP errors preserve their code, message, and data. Native deadline failures become `REQUEST_TIMEOUT`; other gRPC failures become `CONNECTION_CLOSED` with the original status exception as their cause.

The examples and regression tests check both server APIs, progress, subscriptions, multi-round-trip results, concurrent clients with colliding request IDs, caller cancellation, deadlines, runtime shutdown, borrowed-channel closure, and client shutdown during a blocked callback. Cancellation is signalled before handler cleanup begins. Active handlers and callbacks are joined before their owning resources close, including shielded cleanup that takes longer than five seconds. Code that ignores cancellation indefinitely can therefore hold shutdown indefinitely; enforce a hard process deadline in your supervisor rather than closing resources under running code. The SDK's five-second transport and application cleanup deadlines do not replace this join. Invocation metadata and socket peer addresses are not authenticated principals.

Regenerate the protobuf bindings with the pinned compiler:

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples --group dev python -m grpc_tools.protoc --proto_path=examples/transports --python_out=examples/transports --pyi_out=examples/transports examples/transports/mcp_transport_examples/rpc.proto
```

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

## Connection ownership

`demo_mqtt.py` and `demo_amqp.py` contain complete adapter setup. `demo_common.py` runs the same MCP application through either transport.

Each side owns and enters its network client or AMQP channel before entering the transport. Keep the server's network resources alive until `server.serve()` exits. The transport unsubscribes or cancels its consumer, but does not close a borrowed client or channel.

The examples provision a dedicated network connection per logical peer. Both sides agree on a fresh session identifier out of band. They do not implement service discovery, dynamic peer acceptance, or multiplexing many peers through one MQTT messages iterator. Those choices belong in an adapter, not in the SDK dispatcher.

## Wire bindings

| Property | MQTT 5 | AMQP 0.9.1 |
| --- | --- | --- |
| Requests | `mcp/<principal>/<session>/requests` | `mcp.<principal>.<session>.requests` |
| Replies | `mcp/<principal>/<session>/responses` | `mcp.<principal>.<session>.responses` |
| Framing | One JSON-RPC message per publish | One JSON-RPC message per delivery; `application/json` content type |
| Delivery | QoS 2 only | Publisher confirmations; acknowledge before SDK handoff |
| Close | Empty payload | Empty JSON-typed message body |
| Retention | Never retain; do not receive stored retained messages | Nondurable, auto-delete queues |
| Expiry | MQTT message expiry, default 60 seconds | Message TTL and unused queue expiry, default 60 seconds |
| Duplicate handling | MQTT QoS 2 handles protocol retransmissions within its session | Reject redeliveries without requeue |
| Reconnect | Fail pending work; establish a fresh logical connection | Fail pending work; establish a fresh logical connection |

Always use fresh topics or queue names after reconnecting. Do not reuse JSON-RPC request IDs across multiple peers in one SDK stream pair. Server-initiated messages, progress, and cancellation use the same pair of directions; the SDK applies protocol-version restrictions.

Both adapters reject messages larger than `max_message_size`, which defaults to 4 MiB. Malformed messages become recoverable stream exceptions. Connection loss closes the receive stream so the SDK can fail pending calls.

## Delivery limits

QoS 2 and publisher confirmations describe broker delivery, not exactly-once tool execution. Republishing a JSON-RPC request is a new delivery and can repeat a side effect. Neither adapter retries calls automatically.

The AMQP adapter deliberately acknowledges before handing a message to the SDK. A process failure in that window can lose work. Rejecting broker redeliveries avoids automatically rerunning uncertain work, but is not a replacement for application idempotency.

RabbitMQ queues hold at most 256 ready messages and reject publication on overflow. Consumer prefetch bounds unacknowledged deliveries. The MQTT example bounds aiomqtt's incoming queue at 256 messages; aiomqtt can drop messages when that queue fills, so configure client request timeouts and monitor its overflow warnings. This remains a limitation to resolve before claiming reliable saturation behavior. Its publish callback also discards MQTT negative reason codes, so broker rejection may surface only as an MCP request timeout. Neither setting bounds the number of concurrently executing tool handlers.

## Authentication

The local brokers are configured with per-user topic or queue permissions. RabbitMQ cross-peer response consumption was also checked live and rejected. Mosquitto can acknowledge a subscription even when its ACL prevents delivery, so a successful SUBACK is not proof of permission. MQTT authorization-denial checks remain to be automated. The server attaches the principal associated with its configured route; it does not accept an arbitrary reply destination from the message payload.

For production, use TLS and your broker's credential and authorization policy. Include the issuing authority and user in a stable principal identifier. Use `RequestStateSecurity.bind_principal` to bind multi-round-trip state to verified metadata; the SDK does not automatically convert broker identity into an HTTP OAuth token.

The Compose fixtures use public test credentials, listen only on localhost, and disable durable storage. Do not deploy these broker configurations. You can change the local ports with `MQTT_TEST_PORT` and `AMQP_TEST_PORT`; the defaults are 13883 and 15672 respectively.

Both libraries use asyncio. The MQTT provider requires a selector event loop on Windows. Trio and Windows adapter validation have not been completed.

## Validation status

```bash
UV_PROJECT_ENVIRONMENT=examples/transports/.venv uv run --frozen --package mcp-transport-examples --group dev pytest -c examples/transports/pyproject.toml examples/transports/tests --record-mode=none
uv run --frozen pyright --project examples/transports
```

The broker unit tests check configuration failures without opening network connections. The broker programs verify real traffic against Mosquitto and RabbitMQ; they are not cassette-backed CI coverage.

The gRPC tests record real calls with `cassetter` and replay with `--record-mode=none`. They check payload fidelity, progress, and application errors. The tests also compare the serialized requests with the recording: the current gRPC matcher matches only the RPC method, which is insufficient for a generic MCP binding. Each cassette contains one RPC to avoid replaying a newly recorded call as the response to a different request during recording.

The lifecycle, capacity, and malformed-frame regression tests own a gRPC server inside the test process. That server is the software under test, not an external service; replaying its outputs would bypass the behavior being checked. The cassette tests separately compare recorded native results with the current in-process MCP handler and verify request-body fidelity. `cassetter` also lacks parts of the streaming-call cancellation interface, so it is not used to stand in for these live server tests. Binary protobuf payloads are not pattern-scrubbed; inspect new cassettes before committing them. The checked-in recordings contain only public test data.

`cassetter` has no MQTT or AMQP interceptor. Broker record/replay, complete broker-adapter coverage, broker TLS, and cross-platform checks remain open gates. The gRPC implementation and its regression tests have full line and branch coverage on the locally checked interpreters; that does not establish interoperability with another binding or support for repeated event-loop lifetimes. Do not treat a successful live program or cassette replay as evidence for untested server behavior.
