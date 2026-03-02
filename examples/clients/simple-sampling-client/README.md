# Simple Sampling Client

A simple MCP client that demonstrates how to handle **sampling** requests from an MCP server.

## Overview

When an MCP server needs LLM completions during tool execution, it sends a `sampling/createMessage` request to the client. This client provides a `sampling_callback` that handles these requests.

In a real application, the callback would forward the request to an LLM provider (OpenAI, Anthropic, Azure OpenAI, etc.). This example uses a simple demo response for illustration.

## Usage

First, make sure the sampling server is available (install it from `examples/servers/simple-sampling`).

Then run the client:

```bash
uv run mcp-simple-sampling-client
```

## How It Works

1. The client connects to the `mcp-simple-sampling` server via stdio transport.
2. It provides a `sampling_callback` function that handles `sampling/createMessage` requests.
3. When it calls a tool (e.g., `summarize`), the server sends a sampling request back to the client.
4. The client's callback processes the request and returns a response.
5. The server uses that response to complete the tool execution.

## Integrating a Real LLM

To use a real LLM instead of the demo response, replace the body of `handle_sampling` with your LLM call:

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
            type="text", text=response.choices[0].message.content
        ),
        model=response.model,
        stop_reason="endTurn",
    )
```
