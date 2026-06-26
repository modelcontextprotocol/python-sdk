# Sampling

Sampling lets a server ask the client to generate a message with an LLM. The
SDK does not call a model provider by itself. Instead, the client opts in by
registering a `sampling_callback`, and that callback decides which model or
runtime to use.

## Request Flow

1. A server handler calls `ctx.session.create_message(...)`.
2. The SDK sends a `sampling/createMessage` request to the connected client.
3. The client's `sampling_callback` receives a `ClientRequestContext` and
   `CreateMessageRequestParams`.
4. The callback calls the model provider or local runtime that the client owns.
5. The callback returns `CreateMessageResult` to the server.

If the client does not register a sampling callback, sampling requests are
answered with the SDK's default "Sampling not supported" error.

## Register a Client Callback

```python
from mcp import ClientSession, types
from mcp.client.context import ClientRequestContext


async def handle_sampling_message(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    print(f"Sampling request {context.request_id}: {params.messages}")

    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text="Hello from the client model"),
        model="example-model",
        stop_reason="endTurn",
    )


async def run(read_stream, write_stream):
    async with ClientSession(read_stream, write_stream, sampling_callback=handle_sampling_message) as session:
        await session.initialize()
```

The callback may return `types.ErrorData` instead of `CreateMessageResult` when
the user rejects a request or the client cannot fulfill it.

## Model Preferences

`params.model_preferences` is advisory. The server can provide model name hints
or priorities for cost, speed, and intelligence, but the client chooses how to
interpret them.

```python
def pick_model(preferences: types.ModelPreferences | None) -> str:
    if preferences and preferences.hints:
        for hint in preferences.hints:
            if hint.name in {"fast-model", "smart-model"}:
                return hint.name

    if preferences and (preferences.speed_priority or 0) > (preferences.intelligence_priority or 0):
        return "fast-model"

    return "smart-model"
```

Clients can ignore unsupported hints and should still apply their own policy,
such as user approval, model availability, cost limits, or tenant configuration.

## Context Fields

`ClientRequestContext` is request metadata for the callback. It provides:

- `context.session`: the client session handling the request.
- `context.request_id`: the request id, when one is available.
- `context.meta`: optional request metadata.

It is not prompt context and does not automatically add resources or previous
messages to the LLM request.

`params.include_context` is the server's request for additional context. The SDK
passes the value to the callback, but it does not attach context automatically.
The client implementation decides what context it can safely include.

When using `ClientSession` directly, a client that supports non-`none`
`include_context` values can declare that with `sampling_capabilities`:

```python
session = ClientSession(
    read_stream,
    write_stream,
    sampling_callback=handle_sampling_message,
    sampling_capabilities=types.SamplingCapability(context=types.SamplingContextCapability()),
)
```

```python
async def handle_sampling_message(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    model = pick_model(params.model_preferences)
    provider_messages = convert_sampling_messages(params.messages)

    if params.system_prompt:
        provider_messages.insert(0, {"role": "system", "content": params.system_prompt})

    if params.include_context in {"thisServer", "allServers"}:
        extra_context = await load_allowed_context(context, params.include_context)
        provider_messages.insert(0, {"role": "system", "content": extra_context})

    text = await call_your_llm(
        model=model,
        messages=provider_messages,
        max_tokens=params.max_tokens,
        temperature=params.temperature,
        stop_sequences=params.stop_sequences,
        metadata=params.metadata,
    )

    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text=text),
        model=model,
        stop_reason="endTurn",
    )
```

In this example, `convert_sampling_messages`, `load_allowed_context`, and
`call_your_llm` are application-specific helpers. Keeping them outside the SDK
callback makes the example provider-neutral: the same callback shape works with
a hosted model API, a local model runtime, or a test double.
