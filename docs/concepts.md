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

MCP servers expose three core primitives:

### Resources

Resources provide data to LLMs — similar to GET endpoints in a REST API. They load information into the
LLM's context without performing computation or causing side effects.

```python
@mcp.resource("config://app")
def get_config() -> str:
    """Expose application configuration."""
    return json.dumps({"theme": "dark", "version": "2.0"})
```

Resources can be static (fixed URI) or use URI templates for dynamic content:

```python
@mcp.resource("users://{user_id}/profile")
def get_profile(user_id: str) -> str:
    """Get a user profile by ID."""
    return json.dumps(load_profile(user_id))
```

See [Resources](server/resources.md) for full documentation.

### Tools

Tools let LLMs take actions — similar to POST endpoints. They perform computation, call external APIs,
or produce side effects.

```python
@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the given recipient."""
    # ... send email logic ...
    return f"Email sent to {to}"
```

Tools support structured output, progress reporting, and more. See [Tools](server/tools.md) for full documentation.

### Prompts

Prompts are reusable templates for LLM interactions. They help standardize common workflows:

```python
@mcp.prompt()
def review_code(code: str, language: str = "python") -> str:
    """Generate a code review prompt."""
    return f"Review this {language} code:\n\n```{language}\n{code}\n```"
```

See [Prompts](server/prompts.md) for full documentation.

## Transports

MCP supports multiple transport mechanisms for client-server communication:

| Transport | Use case | How it works |
|---|---|---|
| **Streamable HTTP** | Remote servers, production deployments | HTTP POST with optional SSE streaming |
| **stdio** | Local processes, CLI tools | Communication over stdin/stdout |
| **SSE** | Legacy remote servers | Server-Sent Events over HTTP (deprecated in favor of Streamable HTTP) |

See [Running Your Server](server/running.md) for transport configuration.

## Context

When handling requests, your functions can access a **context object** that provides capabilities
like logging, progress reporting, and access to the current session:

```python
from mcp.server.mcpserver import Context

@mcp.tool()
async def long_task(ctx: Context) -> str:
    """A tool that reports progress."""
    await ctx.report_progress(0, 100)
    # ... do work ...
    await ctx.report_progress(100, 100)
    return "Done"
```

Context enables [logging](server/logging.md), [elicitation](server/elicitation.md),
[sampling](server/sampling.md), and more. See [Context](server/context.md) for details.

## Server lifecycle

Servers support a **lifespan** pattern for managing startup and shutdown logic — for example
initializing a database connection pool on startup and closing it on shutdown:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def app_lifespan(server):
    db = await Database.connect()
    try:
        yield {"db": db}
    finally:
        await db.disconnect()

mcp = MCPServer("My App", lifespan=app_lifespan)
```

See [Server](server/index.md) for more on lifecycle management.

## Next steps

- **[Quickstart](quickstart.md)** — build your first server
- **[Server](server/index.md)** — `MCPServer` configuration and lifecycle
- **[Tools](server/tools.md)**, **[Resources](server/resources.md)**, **[Prompts](server/prompts.md)** — dive into each primitive
- **[Client](client/index.md)** — writing MCP clients
- **[Authorization](authorization.md)** — securing your servers with OAuth 2.1
