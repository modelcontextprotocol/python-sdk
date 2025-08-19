# Low-level server examples

The low-level server API provides maximum control over MCP protocol implementation. Use these patterns when you need fine-grained control or when FastMCP doesn't meet your requirements.

## Basic low-level server

Fundamental low-level server patterns:

```python
--8<-- "examples/snippets/servers/lowlevel/basic.py"
```

This example demonstrates:

- Creating a `Server` instance directly
- Manual handler registration with decorators
- Prompt management with `@server.list_prompts()` and `@server.get_prompt()`
- Manual capability declaration
- Explicit initialization and connection handling

## Low-level server with lifespan

Resource management and lifecycle control:

```python
--8<-- "examples/snippets/servers/lowlevel/lifespan.py"
```

This advanced pattern shows:

- Custom lifespan context manager for resource initialization
- Database connection management example
- Accessing lifespan context through `server.request_context`
- Tool implementation with resource access
- Proper cleanup and connection management

## Structured output with low-level API

Manual structured output control:

```python
--8<-- "examples/snippets/servers/lowlevel/structured_output.py"
```

And a standalone implementation:

```python
--8<-- "examples/servers/structured_output_lowlevel.py"
```

These examples cover:

- Manual `outputSchema` definition in tool specifications
- Direct dictionary return for structured data
- Automatic validation against defined schemas
- Backward compatibility with text content

## Simple tool server

Complete low-level server focused on tools:

```python
--8<-- "examples/servers/simple-tool/mcp_simple_tool/server.py"
```

This production-ready example includes:

- Full tool lifecycle management
- Input validation and error handling
- Proper MCP protocol compliance
- Tool execution with structured responses

## Key differences from FastMCP

| Aspect | Low-level API | FastMCP |
|--------|---------------|---------|
| **Control** | Maximum control | Convention over configuration |
| **Boilerplate** | More verbose | Minimal setup |
| **Decorators** | Server method decorators | Simple function decorators |
| **Schema** | Manual definition | Automatic from type hints |
| **Lifecycle** | Manual management | Automatic handling |
| **Best for** | Complex custom logic | Rapid development |

## When to use low-level API

Choose the low-level API when you need:

- Custom protocol message handling
- Complex initialization sequences
- Fine-grained control over capabilities
- Integration with existing server infrastructure
- Performance optimization at the protocol level
- Custom authentication or authorization logic

The low-level API provides the foundation that FastMCP is built upon, giving you access to all MCP protocol features with complete control over implementation details.