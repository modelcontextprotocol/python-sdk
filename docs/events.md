# Events

Events enable server-to-client push notifications over named topics. Clients subscribe to topic patterns, and servers emit events that are delivered to all matching subscribers. Events support MQTT-style wildcard patterns, retained values, and advisory effect hints.

## When to Use Events

Events are designed for:

- Real-time state changes (e.g., a build finished, a file changed)
- Progress or status broadcasts that multiple clients may care about
- Lightweight notifications where a full tool call or resource read is unnecessary

If the client needs to _request_ data, use resources or tools instead. Events are for server-initiated pushes.

## Topic Patterns

Topics are `/`-separated strings with a maximum depth of 8 segments. Clients subscribe using MQTT-style wildcard patterns:

| Pattern | Matches | Does Not Match |
|---------|---------|----------------|
| `build/status` | `build/status` | `build/status/detail` |
| `build/+` | `build/status`, `build/log` | `build/status/detail` |
| `build/#` | `build`, `build/status`, `build/status/detail` | `deploy/status` |
| `+/status` | `build/status`, `deploy/status` | `build/sub/status` |
| `#` | Everything | (matches all topics) |

- `+` matches exactly one segment
- `#` matches zero or more trailing segments (must be the last segment)

## Server-Side

### Declaring Event Topics

Servers declare available topics through `EventTopicDescriptor` entries on the `EventsCapability`. The SDK auto-declares the `events` capability when an `EventSubscribeRequest` handler is registered.

### Emitting Events

Use `ServerSession.emit_event()` to push an event to the connected client:

```python
await server_session.emit_event(
    topic="build/status",
    payload={"project": "myapp", "status": "success"},
)
```

`emit_event()` accepts these keyword arguments:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `topic` | `str` | (required) | Topic string to publish on |
| `payload` | `Any` | (required) | Event data (any JSON-serializable value) |
| `event_id` | `str \| None` | auto-generated ULID | Unique event identifier |
| `timestamp` | `str \| None` | current UTC ISO 8601 | Event timestamp |
| `retained` | `bool` | `False` | Whether to treat as a retained value |
| `source` | `str \| None` | `None` | Opaque source identifier |
| `correlation_id` | `str \| None` | `None` | Links related events together |
| `requested_effects` | `list[EventEffect] \| None` | `None` | Advisory hints for client behavior |
| `expires_at` | `str \| None` | `None` | ISO 8601 expiry for retained values |

### Requested Effects

`EventEffect` provides advisory hints about how the client should handle an event:

```python
from mcp.types import EventEffect

await server_session.emit_event(
    topic="alert/critical",
    payload={"message": "Disk full"},
    requested_effects=[
        EventEffect(type="notify_user", priority="urgent"),
    ],
)
```

| Effect Type | Description |
|-------------|-------------|
| `inject_context` | Suggest injecting the event payload into the LLM context |
| `notify_user` | Suggest notifying the user |
| `trigger_turn` | Suggest triggering an LLM turn |

Priority levels: `low`, `normal` (default), `high`, `urgent`.

### Subscription Registry

`SubscriptionRegistry` manages which sessions are subscribed to which patterns. It handles wildcard matching and guarantees at-most-once delivery per session per event:

```python
from mcp.server.events import SubscriptionRegistry

registry = SubscriptionRegistry()

# Track a session's subscription
await registry.add(session_id, "build/+")

# Find all sessions that should receive an event
matching_sessions = await registry.match("build/status")

# Clean up on disconnect
await registry.remove_all(session_id)
```

### Retained Value Store

`RetainedValueStore` caches the most recent event per topic so new subscribers receive the current state immediately:

```python
from mcp.server.events import RetainedValueStore
from mcp.types import RetainedEvent

store = RetainedValueStore()

# Store a retained value
await store.set(
    "sensor/temperature",
    RetainedEvent(topic="sensor/temperature", eventId="evt-1", payload=22.5),
    expires_at="2025-12-31T23:59:59Z",  # optional expiry
)

# Retrieve retained values matching a pattern
retained = await store.get_matching("sensor/+")
```

Retained values with an `expires_at` in the past are automatically cleaned up on access.

### Handling Subscriptions (Low-Level Server)

Register request handlers for `EventSubscribeRequest`, `EventUnsubscribeRequest`, and `EventListRequest` on the low-level `Server`:

```python
from mcp.server.lowlevel.server import Server, request_ctx
from mcp.server.events import SubscriptionRegistry, RetainedValueStore
from mcp.types import (
    EventSubscribeRequest,
    EventSubscribeResult,
    EventUnsubscribeRequest,
    EventUnsubscribeResult,
    EventListRequest,
    EventListResult,
    EventTopicDescriptor,
    RetainedEvent,
    ServerResult,
    SubscribedTopic,
)

registry = SubscriptionRegistry()
store = RetainedValueStore()

topics = [
    EventTopicDescriptor(pattern="build/+", description="Build events"),
    EventTopicDescriptor(
        pattern="config/current",
        description="Current config",
        retained=True,
    ),
]

server = Server("my-server")


async def handle_subscribe(req: EventSubscribeRequest):
    ctx = request_ctx.get()
    subscribed = []
    for pattern in req.params.topics:
        await registry.add(str(ctx.request_id), pattern)
        subscribed.append(SubscribedTopic(pattern=pattern))

    retained: list[RetainedEvent] = []
    for pattern in req.params.topics:
        retained.extend(await store.get_matching(pattern))

    return ServerResult(
        EventSubscribeResult(subscribed=subscribed, retained=retained)
    )


async def handle_unsubscribe(req: EventUnsubscribeRequest):
    ctx = request_ctx.get()
    for pattern in req.params.topics:
        await registry.remove(str(ctx.request_id), pattern)
    return ServerResult(
        EventUnsubscribeResult(unsubscribed=req.params.topics)
    )


async def handle_list(req: EventListRequest):
    return ServerResult(EventListResult(topics=topics))


server.request_handlers[EventSubscribeRequest] = handle_subscribe
server.request_handlers[EventUnsubscribeRequest] = handle_unsubscribe
server.request_handlers[EventListRequest] = handle_list
```

## Client-Side

### Subscribing to Events

Use `subscribe_events()` to register interest in one or more topic patterns:

```python
result = await session.subscribe_events(["build/+", "deploy/#"])

for sub in result.subscribed:
    print(f"Subscribed: {sub.pattern}")

for rej in result.rejected:
    print(f"Rejected: {rej.pattern} ({rej.reason})")

# Retained values are delivered inline
for event in result.retained:
    print(f"Retained: {event.topic} = {event.payload}")
```

The `EventSubscribeResult` contains:

| Field | Type | Description |
|-------|------|-------------|
| `subscribed` | `list[SubscribedTopic]` | Patterns the server accepted |
| `rejected` | `list[RejectedTopic]` | Patterns the server refused, with reasons |
| `retained` | `list[RetainedEvent]` | Current retained values for subscribed topics |

### Receiving Events

Register a handler to process incoming events. Two approaches:

**Using `set_event_handler()`:**

```python
async def on_event(params: EventParams) -> None:
    print(f"[{params.topic}] {params.payload}")

session.set_event_handler(on_event)
```

**Using the `@on_event` decorator:**

```python
@session.on_event(topic_filter="build/+")
async def on_build_event(params: EventParams) -> None:
    print(f"Build: {params.payload}")
```

The optional `topic_filter` applies an additional client-side filter using the same wildcard syntax as subscription patterns. Events that do not match the filter are silently dropped before reaching the handler.

The client also tracks subscribed patterns internally. Events for topics that do not match any active subscription are dropped, even if the server sends them.

### Unsubscribing

```python
result = await session.unsubscribe_events(["build/+"])
# result.unsubscribed contains the patterns that were removed
```

### Listing Available Topics

```python
result = await session.list_events()
for topic in result.topics:
    print(f"{topic.pattern}: {topic.description} (retained={topic.retained})")
```

## Full Example

A complete server and client exchanging events over an in-memory transport:

```python
import anyio
from mcp.client.session import ClientSession
from mcp.server.events import SubscriptionRegistry
from mcp.server.lowlevel.server import Server, request_ctx
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    EventListRequest,
    EventListResult,
    EventParams,
    EventSubscribeRequest,
    EventSubscribeResult,
    EventTopicDescriptor,
    EventUnsubscribeRequest,
    EventUnsubscribeResult,
    ServerResult,
    SubscribedTopic,
)
import mcp.types as types

registry = SubscriptionRegistry()
descriptors = [EventTopicDescriptor(pattern="chat/+", description="Chat messages")]


def create_server() -> Server:
    server = Server("event-demo")

    async def on_subscribe(req: EventSubscribeRequest):
        ctx = request_ctx.get()
        subscribed = []
        for p in req.params.topics:
            await registry.add("demo", p)
            subscribed.append(SubscribedTopic(pattern=p))
        return ServerResult(EventSubscribeResult(subscribed=subscribed))

    async def on_unsubscribe(req: EventUnsubscribeRequest):
        for p in req.params.topics:
            await registry.remove("demo", p)
        return ServerResult(EventUnsubscribeResult(unsubscribed=req.params.topics))

    async def on_list(req: EventListRequest):
        return ServerResult(EventListResult(topics=descriptors))

    server.request_handlers[EventSubscribeRequest] = on_subscribe
    server.request_handlers[EventUnsubscribeRequest] = on_unsubscribe
    server.request_handlers[EventListRequest] = on_list
    return server


async def main():
    server = create_server()
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage](10)
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage](10)

    received: list[EventParams] = []

    async with (
        ServerSession(
            c2s_recv,
            s2c_send,
            InitializationOptions(
                server_name="demo",
                server_version="0.1.0",
                capabilities=server.get_capabilities(NotificationOptions(), {}),
            ),
        ) as server_session,
        ClientSession(s2c_recv, c2s_send) as client_session,
        anyio.create_task_group() as tg,
    ):

        async def run_server():
            async for msg in server_session.incoming_messages:
                if isinstance(msg, RequestResponder):
                    with msg:
                        handler = server.request_handlers.get(type(msg.request.root))
                        if handler:
                            token = request_ctx.set(
                                types.RequestContext(
                                    request_id=msg.request_id,
                                    meta=msg.request_meta,
                                    session=server_session,
                                    lifespan_context={},
                                )
                            )
                            try:
                                await msg.respond(await handler(msg.request.root))
                            finally:
                                request_ctx.reset(token)

        tg.start_soon(run_server)
        await client_session.initialize()

        # Subscribe and set handler
        await client_session.subscribe_events(["chat/+"])

        @client_session.on_event()
        async def handle(params: EventParams) -> None:
            received.append(params)

        # Server emits an event
        await server_session.emit_event(
            topic="chat/general",
            payload={"user": "alice", "text": "hello"},
        )

        await anyio.sleep(0.1)
        print(f"Received {len(received)} event(s)")
        for ev in received:
            print(f"  [{ev.topic}] {ev.payload}")

        tg.cancel_scope.cancel()


anyio.run(main)
```

## Types Reference

| Type | Description |
|------|-------------|
| `EventParams` | Notification payload: topic, eventId, payload, timestamp, effects |
| `EventEmitNotification` | Server-to-client notification wrapping `EventParams` |
| `EventEffect` | Advisory effect hint (type + priority) |
| `EventTopicDescriptor` | Describes a topic the server can publish to |
| `EventsCapability` | Server capability declaration for events |
| `EventSubscribeParams` | Client request parameters for subscribing |
| `EventSubscribeResult` | Subscribe response: subscribed, rejected, retained |
| `EventUnsubscribeParams` | Client request parameters for unsubscribing |
| `EventUnsubscribeResult` | Unsubscribe response: list of removed patterns |
| `EventListResult` | Response listing available topic descriptors |
| `SubscribedTopic` | A successfully subscribed pattern |
| `RejectedTopic` | A rejected pattern with reason |
| `RetainedEvent` | A cached event delivered on subscribe |
| `SubscriptionRegistry` | Server-side session-to-pattern registry with wildcard matching |
| `RetainedValueStore` | Server-side per-topic retained value cache with expiry |
