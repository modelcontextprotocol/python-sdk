# Concepts

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io) lets you build servers that expose data
and functionality to LLM applications in a standardized way. Think of it like a web API, but specifically
designed for LLM interactions.

## Architecture

MCP follows a client-server architecture:

- **Hosts** are LLM applications (like Claude Desktop or an IDE) that initiate connections
- **Clients** maintain 1:1 connections with servers, inside the host application
- **Servers** provide context, tools, and prompts to clients

```text
Host (e.g. Claude Desktop)
├── Client A ↔ Server A (e.g. file system)
├── Client B ↔ Server B (e.g. database)
└── Client C ↔ Server C (e.g. API wrapper)
```

## Primitives

MCP servers expose three core primitives: **resources**, **tools**, and **prompts**.

### Resources

Resources provide data to LLMs — similar to GET endpoints in a REST API. They load information into the
LLM's context without performing computation or causing side effects.

Resources can be static (fixed URI) or use URI templates for dynamic content:

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")


@mcp.resource("config://app")
def get_config() -> dict[str, str]:
    """Expose application configuration."""
    return {"theme": "dark", "version": "2.0"}


@mcp.resource("users://{user_id}/profile")
def get_profile(user_id: str) -> dict[str, str]:
    """Get a user profile by ID."""
    return {"user_id": user_id, "name": "Alice"}
```

<!-- TODO: See [Resources](server/resources.md) for full documentation. -->

### Tools

Tools let LLMs take actions — similar to POST endpoints. They perform computation, call external APIs,
or produce side effects:

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the given recipient."""
    return f"Email sent to {to}"
```

Tools support structured output, progress reporting, and more.
<!-- TODO: See [Tools](server/tools.md) for full documentation. -->

### Prompts

Prompts are reusable templates for LLM interactions. They help standardize common workflows:

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")


@mcp.prompt()
def review_code(code: str, language: str = "python") -> str:
    """Generate a code review prompt."""
    return f"Please review the following {language} code:\n\n{code}"
```

<!-- TODO: See [Prompts](server/prompts.md) for full documentation. -->

## Transports

MCP supports multiple transport mechanisms for client-server communication:

| Transport | Use case | How it works |
|---|---|---|
| **Streamable HTTP** | Remote servers, production deployments | HTTP POST with optional SSE streaming |
| **stdio** | Local processes, CLI tools | Communication over stdin/stdout |
| **SSE** | Legacy remote servers | Server-Sent Events over HTTP (deprecated in favor of Streamable HTTP) |

<!-- TODO: See [Running Your Server](server/running.md) for transport configuration. -->

## Context

When handling requests, your functions can access a **context object** that provides capabilities
like logging, progress reporting, and access to the current session:

```python
from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer("Demo")


@mcp.tool()
async def long_task(ctx: Context) -> str:
    """A tool that reports progress."""
    await ctx.report_progress(0, 100)
    # ... do work ...
    await ctx.report_progress(100, 100)
    return "Done"
```

Context enables logging, elicitation, sampling, and more.
<!-- TODO: link to server/context.md, server/logging.md, server/elicitation.md, server/sampling.md -->

## Server lifecycle

Servers support a **lifespan** pattern for managing startup and shutdown logic — for example
initializing a database connection pool on startup and closing it on shutdown:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer


@dataclass
class AppContext:
    db_url: str


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    # Initialize on startup
    ctx = AppContext(db_url="postgresql://localhost/mydb")
    try:
        yield ctx
    finally:
        # Cleanup on shutdown
        pass


mcp = MCPServer("My App", lifespan=app_lifespan)
```

<!-- TODO: See [Server](server/index.md) for more on lifecycle management. -->

## Next steps

Continue learning about MCP:

- **[Quickstart](quickstart.md)** — build your first server
- **[Testing](testing.md)** — test your server with the `Client` class
- **[Authorization](authorization.md)** — securing your servers with OAuth 2.1
- **[API Reference](api.md)** — full API documentation
