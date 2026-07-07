# Subscriptions

A server's catalog is not fixed. Tools appear at runtime, and the content behind a resource URI changes.

**Subscriptions** are how a client hears about it. The client sends one `subscriptions/listen` request, and the response to that request *is* the stream: it stays open and carries the change notifications the client asked for.

## Publish it from the tool

Your side of it is one line: publish the change.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` reaches every open stream that subscribed to that URI. Nobody else.
* `await ctx.notify_tools_changed()` reaches every stream that asked for tool-list changes. A client that receives it calls `tools/list` again, and now sees `sprint_report`.
* The siblings are `notify_prompts_changed()` and `notify_resources_changed()`.
* No subscribers, no work. Publishing to an idle server is a no-op, so you never check whether anyone is listening. You state what changed.

`MCPServer` serves `subscriptions/listen` for you. The wire obligations (the acknowledgment as the first frame, per-stream filtering, the subscription id on every frame) are the SDK's job.

!!! check
    On the wire, a stream whose filter named `board://sprint` looks like this after `complete_task` runs:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    Note what the update does *not* carry: the board. Every frame carries the listen request's JSON-RPC id under `_meta`, and that id is the subscription id. This client mints string ids like `"listen-1"`, which is what `sub.subscription_id` returns; other clients may use integers.

## Only what was asked for

The filter is a contract. A stream that requested tool-list changes and one resource URI receives those two kinds and nothing else. Publish a prompt change and that stream stays silent.

`MCPServer` matches resource URIs as exact strings, so a stream that named `board://sprint` hears nothing about `board://sprint/tasks/1`. The spec lets other servers report a change on a sub-resource of a URI you subscribed to, and the client passes those through.

Two things the stream is *not*:

* **It is not a replay log.** A dropped stream is gone, and events published while nobody was connected are not queued. Clients re-listen and refetch.
* **It is not the 2025 path.** Clients that called `resources/subscribe` are served by `ctx.session.send_resource_updated(uri)`. The `notify_*` methods reach `subscriptions/listen` streams only.

!!! warning
    Don't publish sensitive per-user URIs through `notify_resource_updated` on a multi-tenant
    server. Any client may name any URI in its filter, and `MCPServer` honors it. The exposure
    is narrow but real: a subscriber learns that a URI it can guess changed, and when. It never
    learns content, and it cannot probe what exists, because an unknown URI is honored too and
    simply never fires. To narrow the filter per client today, serve the method with your own
    handler on the low-level `Server` and acknowledge a smaller filter than the client asked for.

!!! warning "Streamable HTTP only, for now"
    `subscriptions/listen` needs a transport that can stream a request's response, which today
    means streamable HTTP. Over stdio a 2026-07-28 connection rejects the method with
    METHOD_NOT_FOUND, even though `server/discover` advertises the subscription capabilities
    there. Serving it over stdio is planned; the open-stream semantics for that transport are
    not built yet.

## Watching the stream

On the client, a subscription is one context manager. Entering it sends the request and waits for the server's acknowledgment, so the stream is live by the time the block starts.

```python title="client.py" hl_lines="16 19 29"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Iteration yields four typed events: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged`, and `ResourceUpdated(uri=...)`.

An event says *what* changed, never *how*. That is why `follow_board` calls `read_resource` and `list_tools`: the event is a cue to refetch. Read `event.uri` rather than assuming which resource moved, because once you subscribe to any URI the client delivers every `ResourceUpdated` on the stream.

Duplicate events waiting to be consumed collapse into one, and refetching still gets you the current state. Only identical events collapse: two `ResourceUpdated` for different URIs are two events.

Two more properties of the handle:

* `sub.honored` is the filter the server acknowledged: a `SubscriptionFilter` with the fields you passed, read as attributes (`sub.honored.prompts_list_changed`). `MCPServer` honors every kind you ask for, so it echoes your request back. A server that narrows the filter (see the warning above) acknowledges less, and an honored kind may still never fire.
* `sub.subscription_id` is the listen request's id, the one stamped on every frame of this stream. Several subscriptions can be open at once, each demultiplexed by its own id.

## Watching without blocking

`follow_board` runs until the server closes the stream, which may be never, so on its own it owns your program. Real clients want the watcher *beside* the main flow: an agent calls tools while a watcher keeps a cache or a UI current.

Open the subscription first, then start the watcher and get on with your work.

`app.py` imports `BOARD` and `read_board` from `client.py` above. If you save the files side by side rather than as a package, drop the leading dot from that import.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

The order is the point. Nothing is replayed, so an event published before your stream existed is missed. Entering `client.listen(...)` waits for the acknowledgment, so every change from that moment on reaches your watcher, and the snapshot you take inside the block cannot miss one.

Requests run freely beside an open stream, from the watcher task or any other, on the same client. Because *duplicate* unconsumed events coalesce, a busy main flow may produce one refetch rather than three. Events that differ do not coalesce: a filter naming many URIs queues one pending event per URI.

To stop watching, leave the block: there is no `unsubscribe` call. Cancelling the task that owns the block does that for you, and the SDK sends `notifications/cancelled` for the listen request. A watcher that runs for the life of your app never returns on its own, so cancel it, or its task group's scope, at shutdown.

## Streams end

Both endings are ordinary control flow. A graceful server close ends the `async for`. An abrupt drop raises `SubscriptionLost`.

The difference is diagnostic, not a difference in what to do next: the stream is gone, nothing was replayed, and a watcher that still cares re-listens and refetches.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Servers close streams gracefully for their own reasons, including shedding a subscriber whose backlog grew too large, so a clean end is not a signal to stop watching. Back off before re-listening.

`SubscriptionLost` has one local cause too. The client holds at most 1024 unconsumed events, and a consumer that falls that far behind loses the subscription rather than grow without bound. Keep the body of the `async for` short and do slow work elsewhere.

`keep_following` catches only `SubscriptionLost`. Entering `listen()` can also raise `MCPError` (the connection failed, or the server does not serve the method) and `TimeoutError` (no acknowledgment arrived). Decide which of those your watcher should retry: a `ListenNotSupportedError`, raised on a pre-2026 connection, never heals.

## Scaling past one process

Publishes travel from your handler to the open streams over a `SubscriptionBus`. The default is in-memory: one process, every stream in it. That is the right answer until you run replicas behind a load balancer, because then a client's stream is pinned to one replica, and a publish on another replica has to reach it.

That seam is yours to implement: two methods over your pub/sub backend.

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` is yours, and so is the reader task on each replica that decodes arriving messages and calls every registered listener. Listeners are synchronous, must not raise, and run on the server's event loop.

The bus carries typed `ServerEvent` values, four small dataclasses, never JSON-RPC. Stamping, filtering, and stream lifecycles stay in the SDK, so a bus implementation cannot break the protocol. It can only move events between processes.

To publish from outside a request, construct the bus yourself so you hold the reference. `MCPServer` builds one internally when you pass nothing, and does not expose it.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## The low-level composition

Down on the low-level `Server` there is no pre-wired anything, and the same parts assemble in three lines:

```python title="server.py" hl_lines="10 48"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* You own the bus, so you publish to it directly: `await bus.publish(ResourceUpdated(uri=...))`. Put it wherever your handlers can reach it: module scope here, the lifespan in a bigger app.
* `ListenHandler(bus)` is the same handler `MCPServer` registers, and `on_subscriptions_listen=` is an ordinary handler slot. Put your own callable in that slot for different semantics, and the spec obligations move to you: acknowledge first, stamp every frame with the subscription id, deliver nothing outside the filter.
* `ListenHandler.close()` ends every open stream gracefully. Each one receives the listen request's result as its final frame, which is the spec's way of saying the server ended the subscription deliberately. It returns before those streams finish flushing, so give them a moment before you tear the transport down. Without it, streams end when the client disconnects.

## Recap

* A client opts in with one `subscriptions/listen` request, and the response is the stream. Serving it is built in.
* You publish with `ctx.notify_*`, and the SDK does the stamping, filtering, and lifecycle work.
* Events are cues, not payloads. Both ends refetch.
* Consume with `async with client.listen(...)` and `async for event in sub`. A clean end stops the loop; a drop raises `SubscriptionLost`.
* Open the subscription, then run the watcher as a task, and tool calls keep flowing beside it.
* Scaling out means implementing `SubscriptionBus`, two methods, and passing it as `MCPServer(subscriptions=...)`.

Running the server that serves all this, behind one replica or twenty, is **[Deploy & scale](../run/deploy.md)**.
