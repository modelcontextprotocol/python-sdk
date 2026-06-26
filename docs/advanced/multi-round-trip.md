# Multi-round-trip requests

Sometimes a tool can't finish in one round trip. It needs something only the user has: a choice, a confirmation, a credential.

Before 2026-07-28 the server got it by calling **back**: opening its own request to the client (an elicitation, a sampling call) in the middle of handling the original one. The 2026-07-28 spec retires that back-channel.

Instead, the server **returns**.

## Return, don't call back

The server answers `tools/call` with an **`InputRequiredResult`** instead of a `CallToolResult`. Two of its fields do the work:

* **`input_requests`**: what the server still needs, as a dict keyed by names the server chose. Each value is an `ElicitRequest`, a `CreateMessageRequest`, or a `ListRootsRequest`.
* **`request_state`**: an opaque token. The client echoes it back verbatim on the retry. Your server is the only thing that reads it.

The client fulfils each request, then calls the **same tool again**, carrying its answers in `input_responses` and the token in `request_state`. The server now has what it was missing and returns a normal `CallToolResult`.

That's the whole protocol. Every leg is an ordinary request from the client to the server. Nothing ever flows the other way.

## The server side

The high-level `@mcp.tool()` decorator has no sugar for this yet. Today you write it on the **low-level** `Server`, whose `on_call_tool` handler is allowed to return either result type:

```python title="server.py" hl_lines="44-47"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` is typed `-> CallToolResult | InputRequiredResult`. Returning the second one is the entire server-side API.
* On the first call `params.input_responses` is `None`, so the guard fires and the handler asks instead of answering.
* On the retry, the `ElicitResult` the client sent is sitting under the **same key** (`"region"`) that the server used in `input_requests`.

Everything else in that file (the explicit `input_schema`, the hand-built `CallToolResult`) is the ordinary low-level `Server`, covered in **The low-level Server**. This page only adds the second return type.

## The client side

`Client` runs the loop for you.

Register the callbacks the server might ask for (`elicitation_callback`, `sampling_callback`, `list_roots_callback`) and call the tool. When an `InputRequiredResult` arrives, `Client` dispatches each entry in `input_requests` to the matching callback, retries with the answers and the echoed `request_state`, and keeps going until a `CallToolResult` comes back:

```python title="client.py" hl_lines="12 13"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* That `elicitation_callback` is the same one a pre-2026 server's back-channel `elicitation/create` would have hit. One callback serves both eras.
* `call_tool` returns a plain `CallToolResult`. The intermediate rounds are invisible to the caller.
* `get_prompt` and `read_resource` drive the same loop.

!!! check
    Leave the callback off and the loop fails on the first round: the SDK's stand-in callback
    answers every elicitation with an error, and `call_tool` raises `MCPError` with the message
    *"Elicitation not supported"*.

The loop is bounded. `Client(..., input_required_max_rounds=10)` is the default cap; a server that keeps returning `InputRequiredResult` past it makes `call_tool` raise. If a round carries only `request_state` and no `input_requests`, `Client` sleeps briefly (50ms doubling to a 250ms ceiling) before retrying, so a server that is just saying *"not done yet"* isn't busy-polled.

### Driving the loop yourself

The auto-loop holds nothing between calls. If you need to see each round (to persist `request_state` across a process restart, to show the user what was asked, to bail early) drop to the underlying session, where `allow_input_required=True` hands you the union directly:

```python title="client.py" hl_lines="13 14 20"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` widens the return type to `CallToolResult | InputRequiredResult`. The `isinstance` is what narrows it back.
* `request_state` is now in your hands. Write it down between legs and the conversation can resume from a fresh process.
* For every entry in `input_requests` you put an `InputResponse` under the **same key** in `input_responses`. `fulfil` is where your UI goes; this one hard-codes the answer.
* Same tool name, same `arguments`, every leg. The retry is the original call carried out again, not a new method.

## A 2026-07-28 result

`InputRequiredResult` only exists at protocol version **2026-07-28**. The in-memory `Client(server)` negotiates it for you; over the wire, `mode="auto"` discovers it. After connecting, `client.protocol_version` tells you what you got.

!!! warning
    A pre-2026 session has nowhere to put an `InputRequiredResult`. Return one from your handler on a
    `mode="legacy"` connection and the runner cannot serialize it into the negotiated version; the
    client gets back a `-32603` *"Handler returned an invalid result"* error. A server that serves
    both eras must check `ctx.protocol_version` before reaching for it.

!!! info
    **URL-mode elicitation** rides this exact mechanism on a 2026 connection. The entry in
    `input_requests` is an `ElicitRequest` whose params are `ElicitRequestURLParams`; the user
    finishes the out-of-band flow and your client retries the call. Same loop, no new API. The
    high-level server half is in **Elicitation**.

## Recap

* At 2026-07-28 a server that needs input mid-call **returns** an `InputRequiredResult`. It never opens a request to the client.
* `input_requests` is what it needs. `request_state` is an opaque resume token only the server reads.
* `Client` runs the retry loop for you: register `elicitation_callback` / `sampling_callback` / `list_roots_callback` and `call_tool` returns a plain `CallToolResult`. `input_required_max_rounds` (default 10) bounds it.
* To inspect or persist rounds, use `client.session.call_tool(..., allow_input_required=True)` and own the `while isinstance(result, InputRequiredResult)` loop yourself.
* The server side is the **low-level** `Server` only; `@mcp.tool()` has no sugar for this yet.

This is the mechanism that replaces server-initiated sampling and the rest of the push-style back-channel; see **Deprecated features**.
