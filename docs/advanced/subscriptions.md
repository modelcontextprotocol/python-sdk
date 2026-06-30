# Subscriptions

A server's catalog is not fixed. Tools get registered at runtime, resources change behind their URIs. The client side of that story is a subscription: on the 2026-07-28 protocol, a client that wants to hear about changes sends one `subscriptions/listen` request, and the response to that request *is* the stream — it stays open, carrying exactly the notification kinds the client asked for.

Your side of it is one line: publish the change.

```python title="server.py" hl_lines="16 27"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("note://todo")` delivers `notifications/resources/updated` to every open listen stream that subscribed to that URI. Not to anyone else.
* `await ctx.notify_tools_changed()` delivers `notifications/tools/list_changed` to every stream that asked for tool-list changes. A client that receives it calls `tools/list` again — and now sees `search`.
* The siblings are `notify_prompts_changed()` and `notify_resources_changed()`, for the other two list-changed kinds.
* No subscribers, no work: publishing to an idle server is a no-op. You don't check whether anyone is listening; you state what changed.

The SDK serves `subscriptions/listen` for you — `MCPServer` registers the handler at construction, and the wire obligations (the acknowledgment as the first frame, the per-stream filtering, the subscription id tagged onto every frame) are its job, not yours.

!!! check
    On the wire, a stream whose filter named `note://todo` looks like this after `edit_note` runs:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["note://todo"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": 7}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "note://todo", "_meta": {"io.modelcontextprotocol/subscriptionId": 7}}}
    ```

    The acknowledgment echoes the filter the server agreed to honor, and every frame carries the
    listen request's JSON-RPC id under `_meta` — that id *is* the subscription id.

## Only what was asked for

The filter is a contract. A stream that requested tool-list changes and one resource URI receives those two kinds and nothing else — publish a prompt change and that stream stays silent. Resource URIs are matched as exact strings: `note://todo` does not cover `note://todo/draft`.

Two more things the stream is *not*:

* **It is not a replay log.** A dropped stream is gone; events published while nobody was connected are not queued. The client's contract is to re-listen and re-fetch what it cares about.
* **It is not the 2025 path.** Clients on earlier protocol versions that called `resources/subscribe` are served by `ctx.session.send_resource_updated(uri)` — the `notify_*` methods reach `subscriptions/listen` streams only.

## One process is the default. More takes a bus

Publishes travel from your handler to the open streams over a `SubscriptionBus`. The default is in-memory: one process, every stream in it. That is the right answer until you run replicas behind a load balancer — then a client's stream is pinned to one replica, and a publish on another replica has to reach it.

That seam is yours to implement: two methods over your pub/sub backend.

```python
class RedisSubscriptionBus:
    async def publish(self, event: ServerEvent) -> None:
        await self.redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        ...  # register the local listener; a reader task calls it for arriving events
```

```python
mcp = MCPServer("Notebook", subscriptions=RedisSubscriptionBus(...))
```

The bus carries typed `ServerEvent` values — four small dataclasses — never JSON-RPC. Stamping, filtering, and stream lifecycles stay in the SDK, so a bus implementation cannot break the protocol; it can only move events between processes. The same instance is reachable as `mcp.subscriptions`, which is also how you publish from outside a request: `await mcp.subscriptions.publish(ToolsListChanged())`.

## The low-level composition

Down on the low-level `Server` there is no pre-wired anything — and the same parts assemble in three lines:

```python title="server.py" hl_lines="9 31 39"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* You own the bus, so you publish to it directly: `await bus.publish(ResourceUpdated(uri=...))`. Put it wherever your handlers can reach it — module scope here, the lifespan in a bigger app.
* `ListenHandler(bus)` is the same handler `MCPServer` registers; `on_subscriptions_listen=` is an ordinary handler slot. Don't want the SDK's semantics? Write your own handler for the slot — the spec obligations come with it.
* `ListenHandler.close()` gracefully ends every open stream: each one receives the listen request's result as its final frame, the spec's signal that the server ended the subscription deliberately and the client shouldn't re-listen. Without it, streams end when the client disconnects.

## Recap

* A client opts in with one `subscriptions/listen` request; the response is the stream. There is nothing to configure server-side — serving it is built in.
* You publish: `await ctx.notify_resource_updated(uri)`, `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`. Idle servers make these free.
* Streams receive only what their filter requested; URIs match exactly; nothing is replayed.
* Scaling out means implementing `SubscriptionBus` — two methods — over your own pub/sub, and passing it as `MCPServer(subscriptions=...)`.
* The low-level spelling is the same machinery held in your hands: a bus, `ListenHandler(bus)`, one constructor argument.
