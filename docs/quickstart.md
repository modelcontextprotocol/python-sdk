# Quickstart

This guide will get you up and running with a simple MCP server in minutes.

## Prerequisites

You'll need Python 3.10+ and [uv](https://docs.astral.sh/uv/) (recommended) or pip.

## Create a server

Create a file called `server.py` with a tool, a resource, and a prompt:

```python
from mcp.server.mcpserver import MCPServer

# Create an MCP server
mcp = MCPServer("Demo")


# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting."""
    return f"Hello, {name}!"


# Add a prompt
@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt."""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    return f"{styles.get(style, styles['friendly'])} for someone named {name}."


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

## Run the server

```bash
uv run --with mcp server.py
```

The server starts on `http://localhost:8000/mcp` using Streamable HTTP transport.

## Connect a client

=== "Claude Code"

    Add the server to [Claude Code](https://docs.claude.com/en/docs/claude-code/mcp):

    ```bash
    claude mcp add --transport http my-server http://localhost:8000/mcp
    ```

=== "MCP Inspector"

    Use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to explore your server interactively:

    ```bash
    npx -y @modelcontextprotocol/inspector
    ```

    In the inspector UI, connect to `http://localhost:8000/mcp`.

## Next steps

- **[Concepts](concepts.md)** — understand the protocol architecture and primitives
- **[Testing](testing.md)** — test your server with the `Client` class
- **[API Reference](api.md)** — full API documentation
