# mcp-simple-sampling-client

Companion client for
[`examples/servers/simple-sampling`](../../servers/simple-sampling).
Implements a `sampling_callback` that fulfils server-initiated LLM
requests and honours every advisory field in
`CreateMessageRequestParams`.

## What this example shows

The MCP Python SDK already provides the wiring for sampling, but there
was no end-to-end example of a client that plugs a real LLM into
`ClientSession(sampling_callback=...)`. This client does that and
illustrates:

- Mapping `SamplingMessage` role/content into an OpenAI-compatible chat
  payload.
- Treating `modelPreferences.hints` as soft overrides for model
  selection while logging the numeric priorities.
- Forwarding `systemPrompt`, `temperature`, `maxTokens`,
  `stopSequences` and `metadata` to the LLM provider.
- Logging `includeContext` so users can see the hook point where a
  multi-server client would inject session context.
- Returning `ErrorData` on provider failure instead of letting the
  exception propagate.

## LLM provider

The client speaks the OpenAI-compatible `/chat/completions` schema via
`httpx`, so it works against any gateway that honours that contract:
OpenAI, Groq, OpenRouter, Ollama (`/v1`), vLLM, etc.

Configure it with environment variables:

| Variable           | Default                              | Purpose                                  |
|--------------------|--------------------------------------|------------------------------------------|
| `LLM_API_KEY`      | (required)                           | Bearer token for the provider            |
| `LLM_API_BASE_URL` | `https://api.groq.com/openai/v1`     | Base URL of the chat/completions endpoint|
| `LLM_MODEL`        | `llama-3.3-70b-versatile`            | Fallback model when the server gives no hint |

## Run

From the repository root:

```bash
export LLM_API_KEY=...        # Groq free tier works out of the box
uv run --directory examples/servers/simple-sampling pip install -e . >/dev/null 2>&1 || true
uv run --directory examples/clients/simple-sampling-client \
  mcp-simple-sampling-client --topic "a lighthouse keeper"
```

The client launches the companion server over stdio. You should see:

1. `INFO` line reporting the server's advisory model priorities.
2. The generated story, prefixed with the model name the LLM reports.

## Pointing at a different server

The defaults spawn the companion server, but the flags let you target
any stdio MCP server that issues `sampling/createMessage`:

```bash
mcp-simple-sampling-client \
  --server-command python \
  --server-args "-m your_server_package" \
  --topic "your topic"
```
