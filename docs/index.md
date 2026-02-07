# MCP Python SDK

The **Model Context Protocol (MCP)** allows applications to provide context for LLMs in a standardized way,
separating the concerns of providing context from the actual LLM interaction.

This Python SDK implements the full MCP specification, making it easy to:

- **Build MCP servers** that expose resources, prompts, and tools
- **Create MCP clients** that connect to any MCP server
- **Use standard transports** like stdio, SSE, and Streamable HTTP

## Quick example

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

```bash
uv run --with mcp server.py
```

## Getting started

1. **[Install](installation.md)** the SDK
2. **[Quickstart](quickstart.md)** — build your first MCP server
3. **[Concepts](concepts.md)** — understand the protocol architecture and primitives

## Links

- [MCP specification](https://modelcontextprotocol.io)
- [API Reference](api.md)
- [Migration guide](migration.md) (v1 → v2)
