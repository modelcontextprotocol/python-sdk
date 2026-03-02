# Sampling

Sampling is a powerful MCP feature that allows servers to request LLM completions from the client. Instead of the server needing its own LLM access, it can "borrow" the client's language model to generate text, analyze content, or perform any LLM task.

## How It Works

In a typical MCP interaction, the client calls tools on the server. With sampling, the flow is reversed for part of the interaction:

```text
Client                          Server
  │                               │
  │  call_tool("summarize")       │
  │──────────────────────────────>│
  │                               │
  │  sampling/createMessage       │
  │<──────────────────────────────│
  │                               │
  │  (client calls LLM)          │
  │                               │
  │  CreateMessageResult          │
  │──────────────────────────────>│
  │                               │
  │  tool result                  │
  │<──────────────────────────────│
```

1. The client calls a tool on the server.
2. The server's tool handler sends a `sampling/createMessage` request back to the client.
3. The client's sampling callback processes the request (typically by calling an LLM).
4. The client returns the LLM response to the server.
5. The server uses the response to complete the tool execution.

## Server Side

On the server side, use `ctx.session.create_message()` inside a tool handler to request a completion:

--8<-- "examples/snippets/servers/sampling.py"

The `create_message` method accepts these parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `messages` | `list[SamplingMessage]` | The conversation messages to send |
| `max_tokens` | `int` | Maximum tokens in the response |
| `system_prompt` | `str \| None` | Optional system prompt |
| `temperature` | `float \| None` | Sampling temperature (0.0 = deterministic) |
| `stop_sequences` | `list[str] \| None` | Sequences that stop generation |
| `model_preferences` | `ModelPreferences \| None` | Hints about which model to use |

## Client Side

On the client side, provide a `sampling_callback` when creating the session. This callback handles `sampling/createMessage` requests from the server:

```python
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.context import ClientRequestContext
from mcp.client.stdio import stdio_client


async def handle_sampling(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    # Forward the request to your LLM
    # ... call OpenAI, Anthropic, Azure OpenAI, etc.
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text="LLM response here"),
        model="your-model-name",
        stop_reason="endTurn",
    )


async def main():
    server_params = StdioServerParameters(command="your-server-command")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read,
            write,
            sampling_callback=handle_sampling,
        ) as session:
            await session.initialize()

            # Now when you call a tool that uses sampling,
            # your callback will be invoked automatically
            result = await session.call_tool("summarize", {"text": "..."})
```

### Using the High-Level Client

The `Client` class also supports sampling callbacks:

```python
from mcp import Client

async with Client(server, sampling_callback=handle_sampling) as client:
    result = await client.call_tool("summarize", {"text": "..."})
```

## Integrating with LLM Providers

Here is how to connect the sampling callback to popular LLM providers:

### OpenAI

```python
from openai import AsyncOpenAI

openai_client = AsyncOpenAI()


async def handle_sampling(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    messages = []
    if params.system_prompt:
        messages.append({"role": "system", "content": params.system_prompt})
    for msg in params.messages:
        if isinstance(msg.content, types.TextContent):
            messages.append({"role": msg.role, "content": msg.content.text})

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=params.max_tokens,
        temperature=params.temperature,
    )
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text", text=response.choices[0].message.content or ""
        ),
        model=response.model,
        stop_reason="endTurn",
    )
```

### Anthropic

```python
from anthropic import AsyncAnthropic

anthropic_client = AsyncAnthropic()


async def handle_sampling(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    messages = [
        {"role": msg.role, "content": msg.content.text}
        for msg in params.messages
        if isinstance(msg.content, types.TextContent)
    ]

    response = await anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=messages,
        max_tokens=params.max_tokens or 1024,
        system=params.system_prompt or "",
    )
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text", text=response.content[0].text
        ),
        model=response.model,
        stop_reason="endTurn",
    )
```

## Complete Example

For a complete working example with both server and client, see:

- **Server**: [`examples/servers/simple-sampling`](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers/simple-sampling)
- **Client**: [`examples/clients/simple-sampling-client`](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/clients/simple-sampling-client)

## Model Preferences

Servers can provide hints about which model to use via `model_preferences`:

```python
from mcp.types import ModelPreferences, ModelHint

result = await ctx.session.create_message(
    messages=[...],
    max_tokens=100,
    model_preferences=ModelPreferences(
        hints=[ModelHint(name="claude-sonnet-4-20250514")],
        cost_priority=0.5,
        speed_priority=0.8,
        intelligence_priority=0.7,
    ),
)
```

The client can use these hints to select an appropriate model, but is not required to follow them.
