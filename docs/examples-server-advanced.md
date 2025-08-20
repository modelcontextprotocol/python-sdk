# Advanced server examples

This section covers advanced server patterns including lifecycle management, context handling, and interactive capabilities.

These advanced patterns enable rich, interactive server implementations that go beyond simple request-response workflows.

## Lifespan management

Managing server lifecycle with resource initialization and cleanup:

```python
--8<-- "examples/snippets/servers/lifespan_example.py"
```

This example demonstrates:

- Type-safe lifespan context management
- Resource initialization on startup (database connections, etc.)
- Automatic cleanup on shutdown
- Accessing lifespan context from tools via [`ctx.request_context.lifespan_context`][mcp.server.fastmcp.Context.request_context]

## User interaction and elicitation

Tools that can request additional information from users:

```python
--8<-- "examples/snippets/servers/elicitation.py"
```

This example shows:

- Using [`ctx.elicit()`][mcp.server.fastmcp.Context.elicit] to request user input
- Pydantic schemas for validating user responses
- Handling user acceptance, decline, or cancellation
- Interactive booking workflow patterns

## LLM sampling and integration

Tools that interact with LLMs through sampling:

```python
--8<-- "examples/snippets/servers/sampling.py"
```

This demonstrates:

- Using [`ctx.session.create_message()`][mcp.server.session.ServerSession.create_message] for LLM interaction
- Structured message creation with [`SamplingMessage`][mcp.types.SamplingMessage] and [`TextContent`][mcp.types.TextContent]
- Processing LLM responses within tools
- Chaining LLM interactions for complex workflows

## Logging and notifications

Advanced logging and client notification patterns:

```python
--8<-- "examples/snippets/servers/notifications.py"
```

This example covers:

- Multiple log levels (debug, info, warning, error)
- Resource change notifications via [`ctx.session.send_resource_list_changed()`][mcp.server.session.ServerSession.send_resource_list_changed]
- Contextual logging within tool execution
- Client communication patterns

## Image handling

Working with images in MCP servers:

```python
--8<-- "examples/snippets/servers/images.py"
```

This shows:

- Using FastMCP's [`Image`][mcp.server.fastmcp.Image] class for automatic image handling
- PIL integration for image processing with [`PIL.Image.open()`][PIL.Image.open]
- Returning images from tools
- Image format conversion and optimization

## Completion support

Providing argument completion for enhanced user experience:

```python
--8<-- "examples/snippets/servers/completion.py"
```

This advanced pattern demonstrates:

- Dynamic completion based on partial input
- Context-aware suggestions (repository suggestions based on owner)
- Resource template parameter completion
- Prompt argument completion
