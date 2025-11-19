## Why this

This is an example of markitdown in "homebrew" style.

## Features

A MCP server on my laptop and agent on my mobile phone.
Pass files from my mobile phone to my laptop through this.

## Out of scope

- Trust and security, no need as a "homebrew" for individual usage.
- Persistent storage, no need as a "homebrew" for individual usage.
- stdio, as share files among different devices, network.

## Installation, Usage and Example

```bash
# Navigate to the server directory
cd examples/servers/homebrewupload

# Start MCP server
uv run python main.py
```

move to `examples/clients/homebrewupload-client`

## Further consideration

As if we running it as container, then on k8s, we can use service mesh and etc to handle with security as AA.
