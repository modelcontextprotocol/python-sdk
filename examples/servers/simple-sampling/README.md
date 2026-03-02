# Simple Sampling Server

A simple MCP server that demonstrates the **sampling** feature. Sampling allows a server to request LLM completions from the connected client, effectively "borrowing" the client's language model.

## Overview

This server exposes two tools that use sampling:

- **`summarize`** — Sends a text to the client's LLM and asks for a concise summary.
- **`analyze_sentiment`** — Sends a text to the client's LLM and asks for sentiment analysis (positive, negative, or neutral).

When a client calls either tool, the server sends a `sampling/createMessage` request back to the client. The client's sampling callback processes this request (typically by forwarding it to an LLM) and returns the result.

## Usage

Start the server:

```bash
uv run mcp-simple-sampling
```

## How Sampling Works

1. The client calls a tool on the server (e.g., `summarize`).
2. Inside the tool handler, the server calls `ctx.session.create_message(...)` with messages and parameters.
3. The SDK sends a `sampling/createMessage` request to the client.
4. The client's `sampling_callback` processes the request and returns a `CreateMessageResult`.
5. The server receives the result and uses it to complete the tool execution.

## Paired Client

See [`examples/clients/simple-sampling-client`](../../clients/simple-sampling-client/) for a client that connects to this server and provides a sampling callback.
