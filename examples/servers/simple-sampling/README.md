# mcp-simple-sampling

Minimal MCP server that demonstrates server-initiated **sampling** — the
protocol feature that lets a server ask its client to run an LLM on its
behalf.

Exposes a single tool, `write_story`, that delegates text generation to
the client via `sampling/createMessage`. The request is populated with
every advisory field the spec defines (`modelPreferences`,
`systemPrompt`, `temperature`, `stopSequences`, `includeContext`,
`metadata`) so the companion client in
`examples/clients/simple-sampling-client` can show how to interpret
them.

## Run

Clients typically launch the server via stdio, so you don't run this
process yourself. If you want to smoke-test it manually:

```bash
uv run mcp-simple-sampling --transport streamable-http --port 8000
```

For the normal stdio usage, see the client README.
