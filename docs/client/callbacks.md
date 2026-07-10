# Client callbacks

Nearly every request in MCP goes one way: client to server.

A server can also ask the **client** for things: to put a question to the user, to sample the user's model, to list the user's workspace folders. You answer those requests by passing **callbacks** to `Client(...)`.

## A server that asks

Here is a server whose tool can't finish on its own:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` sends an `elicitation/create` request **to the client** and waits.
* The tool doesn't return until somebody (a person in a form, or your code) supplies a `name`.

That is the server half, and the **[Elicitation](../handlers/elicitation.md)** page owns it. This page is the other end of the wire.

## The elicitation callback

```python title="client.py" hl_lines="7-11 17-18"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* An elicitation callback is `async (context, params) -> ElicitResult`.
* `params.message` is the question. `params.requested_schema` is the JSON Schema of the answer the server wants. A real client renders a form from it; this one auto-fills.
* You return `ElicitResult(action="accept", content={...})`, or `action="decline"`, or `action="cancel"`. The only other option is `ErrorData(...)`, which refuses the request and fails the whole call.
* `context` is a `ClientRequestContext`: the live `session`, the server's `request_id`, and any `meta` it attached.

!!! tip
    `params` is a union of the two elicitation modes. Here `params.mode` is `"form"`; a `"url"` request
    carries `params.url` instead of a schema. One callback handles both; branch on `params.mode`.
    **[Elicitation](../handlers/elicitation.md)** shows the full pattern.

### Try it

Call `issue_card` and watch both ends.

Your callback receives the server's question, already parsed:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

It answers, `ctx.elicit(...)` resumes inside the tool, and the tool finishes:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

One `tools/call` from you, one `elicitation/create` back from the server, answered by your function, all inside a single tool call.

!!! info
    `mode="legacy"` on line 17 is doing real work. By default `Client(...)` negotiates the modern
    protocol path, and that path has no back-channel for server-to-client requests: `ctx.elicit`
    fails before your callback ever runs. The transport doesn't decide that; the negotiated
    protocol does, in-memory and over a URL alike. Pin `mode="legacy"` whenever your client has
    to answer one; every test behind this page does. **[Protocol versions](../protocol-versions.md)** has the whole story.

    On a 2026-07-28 session the callback isn't dead, it's fed differently: when a tool returns an
    `InputRequiredResult` carrying an `ElicitRequest`, `Client` dispatches that entry to the same
    `elicitation_callback` and retries the call for you. That flow is **[Multi-round-trip requests](../handlers/multi-round-trip.md)**.

## A callback is a capability

You never told the server that your client can answer elicitation requests. The SDK did.

When a client connects it declares its `capabilities`, the mirror image of the server's. You don't write that object. **Registering a callback is the declaration.**

| you pass | the client declares |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| none of them | `{}` |

Sampling sub-capabilities are the one refinement: pass `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` alongside `sampling_callback` when your sampler handles the `tools` / `tool_choice` parameters. Servers must see `sampling.tools` declared before they can send them.

`logging_callback` and `message_handler` are not in the table. They handle notifications, and notifications need no capability.

The server reads the declaration back with `ctx.session.check_client_capability(...)`. Add a tool that does:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

Connect with only `elicitation_callback` and call it:

```python
result.structured_content  # {'result': ['elicitation']}
```

Pass all three callbacks and you get `['elicitation', 'sampling', 'roots']`. Pass none and you get `[]`.

!!! check
    Now do the wrong thing: connect **without** `elicitation_callback` and call `issue_card` anyway.

    The server's `elicitation/create` request still reaches your client, and the SDK answers it for
    you, with an error, because you never said you could handle it. That error sinks the whole call.
    `call_tool` doesn't return an `is_error` result; it raises:

    ```text
    MCPError: Elicitation not supported
    ```

    That is a protocol error (`-32600`, *invalid request*), not a tool error: there is nothing for
    the model to read and retry. It's why `client_features` is worth having: a well-behaved server
    checks before it asks.

## The deprecated pair

`sampling_callback` answers `sampling/createMessage`: the server asking *your* model to complete something. `list_roots_callback` answers `roots/list`: the server asking which directories it may work in.

Both work. Both follow the rule above. And both serve RPCs the **2026-07-28 spec removes**: a modern server doesn't call back into your client mid-request, it hands the request back to you as part of the tool result (**[Multi-round-trip requests](../handlers/multi-round-trip.md)**). The callbacks themselves are not dead. When an `InputRequiredResult` carries a `CreateMessageRequest` or a `ListRootsRequest`, `Client`'s auto-loop dispatches it to the same `sampling_callback` or `list_roots_callback` you registered here. The whole list is in **[Deprecated features](../deprecated.md)**.

You still need the callbacks to talk to servers that haven't moved. The signatures:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* A sampling callback receives the full `CreateMessageRequestParams` (`messages`, `model_preferences`, `max_tokens`) and returns a `CreateMessageResult`. *You* run the model, however you like; the SDK only carries the request.
* A roots callback takes no params at all and returns a `ListRootsResult`.
* Either one may return `ErrorData(...)` instead, to refuse.

Pass them to `Client(...)` exactly like `elicitation_callback`.

## The notification callbacks

Two more. Neither declares anything.

`logging_callback` receives every `notifications/message` a server sends, as `LoggingMessageNotificationParams` (`level`, `logger`, `data`). Protocol logging is itself deprecated by the 2026-07-28 spec (**[Logging](../handlers/logging.md)** has what to do instead), so this callback exists for the servers that still emit it.

`message_handler` is the catch-all: every server notification reaches it (as well as its specific callback), and on a stream-backed transport so does every transport-level `Exception`. The one pattern worth knowing is `if isinstance(message, Exception): raise message`, so a broken connection fails loudly instead of vanishing.

## Recap

* A server can send requests to the client. You answer them with callbacks passed to `Client(...)`.
* The elicitation callback is the current one: `async (context, params) -> ElicitResult`, one function for both form and URL mode.
* **Registering a callback is declaring the capability.** Without it, the SDK refuses the server's request on your behalf and the whole call fails with `MCPError`.
* A server finds out before asking with `ctx.session.check_client_capability(...)`.
* `sampling_callback` and `list_roots_callback` work the same way but serve deprecated features; modern servers use multi-round-trip requests instead.
* `logging_callback` and `message_handler` receive notifications. They declare nothing.

The first argument to `Client(...)` is a transport object. **[Client transports](transports.md)** covers every kind.
