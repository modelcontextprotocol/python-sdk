# Server resources examples

Resources provide data to LLMs without side effects. They're similar to GET endpoints in REST APIs and should be used for exposing information rather than performing actions.

Resources are essential for providing contextual information to LLMs, whether it's configuration data, file contents, or dynamic information that changes over time.

## Basic resources

Simple resource patterns for exposing data:

```python
--8<-- "examples/snippets/servers/basic_resource.py"
```

This example demonstrates:

- Static resources with fixed URIs (`config://settings`)
- Dynamic resources with URI templates (`file://documents/{name}`)
- Simple string data return
- JSON configuration data

## Simple resource server

A complete server focused on resource management:

```python
--8<-- "examples/servers/simple-resource/mcp_simple_resource/server.py"
```

This is an example of a low-level server that:

- Uses the low-level server API for maximum control
- Implements resource listing and reading
- Handles URI templates and parameter extraction
- Demonstrates production-ready resource patterns


## Memory and state management

Resources that manage server memory and state:

```python
--8<-- "examples/fastmcp/memory.py"
```

This example shows how to:

- Implement persistent memory across requests
- Store and retrieve conversational context
- Handle memory cleanup and management
- Provide memory resources to LLMs
