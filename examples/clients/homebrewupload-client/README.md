## Why this

This is an example of markitdown in "homebrew" style.

## Features

A MCP server on my laptop and agent on my mobile phone.
Pass files from my mobile phone to my laptop through this.

## Out of scope

- Trust and security, no need as a "homebrew" for individual usage.
- Persistent storage, no need as a "homebrew" for individual usage.
- stdio, as share files among different devices, network.

## Prerequest

See `examples/servers/homebrewupload`

## Installation, Usage and Example

```bash
# todo
# Navigate to the server directory
cd examples/clients/homebrewupload-client

# You need to make a pdf file as test.pdf
# examples/clients/homebrewupload-client/test.pdf

## defualt tested with DeepSeek as LLM provider
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_API_KEY=<Your_API_KEY>

# Start MCP server
uv run python main.py
```

## Token cosumption discussion

In auther's local test, auther use a pdf with content as `hello world`.
When using data style URI `data...base64...` it consumes about 30k token after base64.
When using this example, using `file:...path...` instead.
Which impls execution out of LLM context, just consumes about token on file path and `hello world`.
