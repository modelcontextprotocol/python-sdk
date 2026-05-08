# Environment Variables

MCP servers commonly need access to API keys, database URLs, and other configuration.
This guide covers the patterns for passing and accessing environment variables.

## Accessing Environment Variables in Tools

Use `os.environ` or `os.getenv()` to read environment variables in your tool functions:

```python title="server.py"
import os

from mcp.server import MCPServer

mcp = MCPServer("my-server")


@mcp.tool()
def search(query: str) -> str:
    """Search using an external API."""
    api_key = os.environ["SEARCH_API_KEY"]  # (1)!
    # use api_key to call your service...
    return f"Results for: {query}"


@mcp.tool()
def summarize(text: str) -> str:
    """Summarize text using the configured model."""
    model = os.getenv("MODEL_NAME", "gpt-4o")  # (2)!
    return f"Summary (via {model}): {text[:100]}..."
```

1. Raises `KeyError` if the variable is not set. Use this for required configuration.
2. Returns a default value if the variable is not set. Use this for optional configuration.

## How Environment Variables Reach Your Server

### Claude Desktop

When configuring a server in Claude Desktop's `claude_desktop_config.json`,
environment variables are specified in the `env` field:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uv",
      "args": ["run", "server.py"],
      "env": {
        "SEARCH_API_KEY": "sk-...",
        "MODEL_NAME": "gpt-4o"
      }
    }
  }
}
```

The `mcp install` command can set these for you:

```bash
# Set individual variables
mcp install server.py -v SEARCH_API_KEY=sk-... -v MODEL_NAME=gpt-4o

# Or load from a .env file
mcp install server.py -f .env
```

### Running Directly

When running your server directly, pass environment variables using standard shell mechanisms:

```bash
# Inline
SEARCH_API_KEY=sk-... uv run server.py

# Or export first
export SEARCH_API_KEY=sk-...
uv run server.py
```

### Programmatic Clients

When connecting to a stdio server programmatically, pass environment variables
through `StdioServerParameters`:

```python
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

params = StdioServerParameters(
    command="uv",
    args=["run", "server.py"],
    env={
        "SEARCH_API_KEY": "sk-...",
        "MODEL_NAME": "gpt-4o",
    },
)

async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # session is ready to use
```

!!! note
    The stdio transport inherits a filtered set of environment variables from the parent
    process for security. Variables passed via the `env` parameter are merged on top of
    these defaults.

## MCPServer Settings

`MCPServer` uses [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
and recognizes the following `MCP_`-prefixed environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DEBUG` | `false` | Enable debug logging |
| `MCP_LOG_LEVEL` | `INFO` | Set the log level |
| `MCP_WARN_ON_DUPLICATE_TOOLS` | `true` | Warn when registering duplicate tool names |
| `MCP_WARN_ON_DUPLICATE_RESOURCES` | `true` | Warn when registering duplicate resources |
| `MCP_WARN_ON_DUPLICATE_PROMPTS` | `true` | Warn when registering duplicate prompts |

These can also be set in a `.env` file, which `MCPServer` loads automatically.
