# MCP Python SDK

The **Model Context Protocol (MCP)** allows applications to provide context for LLMs in a standardized way, separating the concerns of providing context from the actual LLM interaction.

This Python SDK implements the full MCP specification, making it easy to:

- **Build MCP servers** that expose resources, prompts, and tools
- **Create MCP clients** that can connect to any MCP server
- **Use standard transports** like stdio, SSE, and Streamable HTTP

If you want to read more about the specification, please visit the [MCP documentation](https://modelcontextprotocol.io).

## Quick Example

Here's a simple MCP server that exposes a tool, resource, and prompt:

```python title="server.py"
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Test Server")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"


@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt"""
    return f"Write a {style} greeting for someone named {name}."
```

Test it with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
uv run mcp dev server.py
```

## Getting Started

<!-- TODO(Marcelo): automatically generate the follow references with a header on each of those files. -->
1. **[Install](installation.md)** the MCP SDK
2. **[Learn concepts](concepts.md)** - understand the three primitives and architecture
3. **[Explore authorization](authorization.md)** - add security to your servers
4. **[Use low-level APIs](low-level-server.md)** - for advanced customization

## API Reference

Full API documentation is available in the [API Reference](api.md).
