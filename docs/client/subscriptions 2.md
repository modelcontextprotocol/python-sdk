# Subscriptions

A server's catalog is not fixed. Tools appear at runtime, and the content behind a resource URI changes. A client hears about it through `client.listen(...)`: one `subscriptions/listen` request whose response *is* the stream. It stays open and carries the change notifications the client asked for.

This page is the client end: opening the stream, watching it beside your main flow, and handling its endings. Publishing changes, filtering, and serving the method are the server's side of the story, told in **[Subscriptions](../handlers/subscriptions.md)** under *Inside your handler*. The examples here talk to the sprint-board server built there.

## Watching the stream

A subscription is one context manager. Entering it sends the request, with your keyword arguments as the subscription filter, and waits for the server's acknowledgment, so the stream is live by the time the block starts.

```python title="client.py" hl_lines="16 19 29"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Iteration yields four typed events: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged`, and `ResourceUpdated(uri=...)`.

An event says *what* changed, never *how*. That is why `follow_board` calls `read_resource` and `list_tools`: the event is a cue to refetch. Read `event.uri` rather than assuming which resource moved: a filter can name several URIs, and a server may report a change on a sub-resource of one of them.

Duplicate events waiting to be consumed collapse into one, and refetching still gets you the current state. Only identical events collapse: two `ResourceUpdated` for different URIs are two events.

Two more properties of the handle:

* `sub.honored` is the filter the server acknowledged: a `SubscriptionFilter` with the fields you passed, read as attributes (`sub.honored.prompts_list_changed`). `MCPServer` honors every kind you ask for, so it echoes your request back. A server that narrows the filter (see the [filter warning](../handlers/subscriptions.md#only-what-was-asked-for) on the server page) acknowledges less, and an honored kind may still never fire.
* `sub.subscription_id` is the listen request's id, the one stamped on every frame of this stream. Several subscriptions can be open at once, each demultiplexed by its own id.

## Watching without blocking

`follow_board` runs until the server closes the stream, which may be never, so on its own it owns your program. Real clients want the watcher *beside* the main flow: an agent calls tools while a watcher keeps a cache or a UI current.

Open the subscription first, then start the watcher and get on with your work.

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

!!! note
    `app.py` imports `BOARD` and `read_board` from the first example, which this repo stores as
    `tutorial003.py`. If you save the rendered files side by side as `client.py` and `app.py`,
    write `from client import BOARD, read_board` instead. The `watch.py` example further down
    imports `read_board` the same way.

The order is the point. Nothing is replayed, so an event published before your stream existed is missed. Entering `client.listen(...)` waits for the acknowledgment, so every change from that moment on reaches your watcher, and the snapshot you take inside the block cannot miss one.

Requests run freely beside an open stream, from the watcher task or any other, on the same client. Because *duplicate* unconsumed events coalesce, a busy main flow may produce one refetch rather than three. Events that differ do not coalesce: a filter naming many URIs queues one pending event per URI.

To stop watching, leave the block: there is no `unsubscribe` call. Cancelling the task that owns the block does that for you, and the SDK cancels the listen request the way the transport expects: over streamable HTTP, by closing that request's stream. A watcher that runs for the life of your app never returns on its own, so cancel it, or its task group's scope, at shutdown.

## Streams end

A stream ends in one of two ways, both ordinary control flow. A graceful server close ends the `async for`; an abrupt drop raises `SubscriptionLost`.

The difference is diagnostic, not a difference in what to do next: the stream is gone, nothing was replayed, and a watcher that still cares re-listens and refetches.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Servers close streams gracefully for their own reasons, including shedding a subscriber whose backlog grew too large, so a clean end is not a signal to stop watching. Back off before re-listening.

`SubscriptionLost` has one local cause too. The client holds at most 1024 unconsumed events, and a consumer that falls that far behind loses the subscription rather than grow without bound. Keep the body of the `async for` short and do slow work elsewhere.

`keep_following` catches only `SubscriptionLost`. Entering `listen()` can also raise `MCPError` (the connection failed, or the server does not serve the method), `TimeoutError` (no acknowledgment arrived), and `ListenNotSupportedError` (a pre-2026 connection). Decide which of those your watcher should retry: the last never heals.

## Recap

* Enter `async with client.listen(...)`; entering waits for the acknowledgment, so nothing published after it is missed.
* Iterate with `async for event in sub`. Events are cues to refetch, never payloads.
* Open the subscription, then run the watcher as a task, and tool calls keep flowing beside it.
* A clean end stops the loop; a drop raises `SubscriptionLost`. Either way: re-listen, refetch, back off first.
* Leaving the block is the unsubscribe.

Publishing these events, narrowing the filter, and scaling past one process are the server's story: **[Subscriptions](../handlers/subscriptions.md)**. These same events also keep a client-side cache honest, and **[Caching](caching.md)** is the next page.
