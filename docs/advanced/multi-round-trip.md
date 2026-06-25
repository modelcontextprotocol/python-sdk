# Multi-round-trip requests

Sometimes a tool can't finish in one round trip. It needs something only the user has — a choice, a confirmation, a credential.

Before 2026-07-28 the server got it by calling **back**: opening its own request to the client (an elicitation, a sampling call) in the middle of handling the original one. The 2026-07-28 spec retires that back-channel.

Instead, the server **returns**.

## Return, don't call back

The server answers `tools/call` with an **`InputRequiredResult`** instead of a `CallToolResult`. Two of its fields do the work:

* **`input_requests`** — what the server still needs, as a dict keyed by names the server chose. Each value is an `ElicitRequest`, a `CreateMessageRequest`, or a `ListRootsRequest`.
* **`request_state`** — an opaque token. The client echoes it back verbatim on the retry. Your server is the only thing that reads it.

The client fulfils each request, then calls the **same tool again**, carrying its answers in `input_responses` and the token in `request_state`. The server now has what it was missing and returns a normal `CallToolResult`.

That's the whole protocol. Every leg is an ordinary request from the client to the server. Nothing ever flows the other way.

## The server side

The high-level `@mcp.tool()` decorator has no sugar for this yet. Today you write it on the **low-level** `Server`, whose `on_call_tool` handler is allowed to return either result type:

```python title="server.py" hl_lines="44-47"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` is typed `-> CallToolResult | InputRequiredResult`. Returning the second one is the entire server-side API.
* On the first call `params.input_responses` is `None`, so the guard fires and the handler asks instead of answering.
* On the retry, the `ElicitResult` the client sent is sitting under the **same key** — `"region"` — that the server used in `input_requests`.

Everything else in that file — the explicit `input_schema`, the hand-built `CallToolResult` — is the ordinary low-level `Server`, covered in **The low-level Server**. This page only adds the second return type.

## The client side

`call_tool` will not hand you an `InputRequiredResult` unless you opt in.

!!! check
    Call a tool that needs input without opting in and `call_tool` raises:

    ```text
    Server returned InputRequiredResult; pass allow_input_required=True to receive it and retry call_tool(..., input_responses=..., request_state=result.request_state).
    ```

    That is deliberate. Most call sites expect a result or an exception, not a third thing in the
    middle of the happy path — and pyright agrees: without the flag, `call_tool` is typed to return
    a plain `CallToolResult`.

Pass `allow_input_required=True` and the result reaches you intact:

```python
result.result_type     # 'input_required'
result.request_state   # 'provision-v1'
result.input_requests  # {'region': ElicitRequest(method='elicitation/create', params=ElicitRequestFormParams(...))}
```

### The retry loop

Now you own the loop. There is no automatic driver yet — `while isinstance(result, InputRequiredResult)` **is** the API:

```python title="client.py" hl_lines="13-15 17-20"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `allow_input_required=True` widens the return type to `CallToolResult | InputRequiredResult`. That union is exactly what the `isinstance` is narrowing.
* For every entry in `input_requests` you put an `InputResponse` under the **same key** in `input_responses`. `fulfil` is where your UI goes; this one hard-codes the answer.
* Same tool name, same `arguments`, every leg. The retry is the original call carried out again, not a new method.
* `request_state=result.request_state` — copy it across. Never inspect it, never invent it.
* When the server has everything it needs it returns a `CallToolResult` and the loop exits.

## A 2026-07-28 result

`InputRequiredResult` only exists at protocol version **2026-07-28**. The in-memory `Client(server)` negotiates it for you; over the wire, `mode="auto"` discovers it. After connecting, `client.protocol_version` tells you what you got.

!!! warning
    A pre-2026 session has nowhere to put an `InputRequiredResult`. Return one from your handler on a
    `mode="legacy"` connection and the runner cannot serialize it into the negotiated version — the
    client gets back a `-32603` *"Handler returned an invalid result"* error. A server that serves
    both eras must check `ctx.protocol_version` before reaching for it.

!!! info
    **URL-mode elicitation** rides this exact mechanism on a 2026 connection. The entry in
    `input_requests` is an `ElicitRequest` whose params are `ElicitRequestURLParams`; the user
    finishes the out-of-band flow and your client retries the call. Same loop, no new API — the
    high-level server half is in **Elicitation**.

## Recap

* At 2026-07-28 a server that needs input mid-call **returns** an `InputRequiredResult`. It never opens a request to the client.
* `input_requests` is what it needs. `request_state` is an opaque resume token only the server reads.
* The client answers by calling the **same tool again** with `input_responses=` and `request_state=`.
* By default `call_tool` raises on an `InputRequiredResult`; `allow_input_required=True` opts in and widens the return type.
* The manual `while isinstance(result, InputRequiredResult)` loop is the whole client API — there is no auto-retry driver yet.
* The server side is the **low-level** `Server` only; `@mcp.tool()` has no sugar for this yet.

This is the mechanism that replaces server-initiated sampling and the rest of the push-style back-channel — see **Deprecated features**.
