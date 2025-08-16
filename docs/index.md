# MCP Python SDK

A Python implementation of the Model Context Protocol (MCP) that enables applications to provide context for LLMs in a standardized way.

## Overview

The Model Context Protocol allows you to build servers that expose data and functionality to LLM applications securely. This Python SDK implements the full MCP specification with both high-level FastMCP and low-level server implementations.

### Key features

- **FastMCP server framework** - High-level, decorator-based server creation
- **Multiple transports** - stdio, SSE, and Streamable HTTP support
- **Type-safe development** - Full type hints and Pydantic integration
- **Authentication support** - OAuth 2.1 resource server capabilities
- **Rich tooling** - Built-in development and deployment utilities

## Quick start

Create a simple MCP server in minutes:

```python
from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"
```

Install in Claude Desktop:

```bash
uv run mcp install server.py
```

## Documentation sections

### Getting started
- **[Quickstart](quickstart.md)** - Build your first MCP server
- **[Installation](installation.md)** - Setup and dependencies

### Core concepts
- **[Servers](servers.md)** - Server creation and lifecycle management
- **[Resources](resources.md)** - Exposing data to LLMs
- **[Tools](tools.md)** - Creating LLM-callable functions
- **[Prompts](prompts.md)** - Reusable interaction templates
- **[Context](context.md)** - Request context and capabilities

### Advanced features
- **[Images](images.md)** - Working with image data
- **[Authentication](authentication.md)** - OAuth 2.1 implementation
- **[Sampling](sampling.md)** - LLM text generation
- **[Elicitation](elicitation.md)** - User input collection
- **[Progress & logging](progress-logging.md)** - Status updates and notifications

### Transport & deployment
- **[Running servers](running-servers.md)** - Development and production deployment
- **[Streamable HTTP](streamable-http.md)** - Modern HTTP transport
- **[ASGI integration](asgi-integration.md)** - Mounting to existing web servers

### Client development
- **[Writing clients](writing-clients.md)** - MCP client implementation
- **[OAuth for clients](oauth-clients.md)** - Client-side authentication
- **[Display utilities](display-utilities.md)** - UI helper functions
- **[Parsing results](parsing-results.md)** - Handling tool responses

### Advanced usage
- **[Low-level server](low-level-server.md)** - Direct protocol implementation
- **[Structured output](structured-output.md)** - Advanced type patterns
- **[Completions](completions.md)** - Argument completion system

## API reference

Complete API documentation is auto-generated from the source code and available in the [API Reference](reference/) section.
