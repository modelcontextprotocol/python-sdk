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

## defualt tested with DeepSeek as LLM provider
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_API_KEY=<Your_API_KEY>

# Start MCP server
uv run python main.py
```


