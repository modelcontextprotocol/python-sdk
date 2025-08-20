# Client examples

MCP clients connect to servers to access tools, resources, and prompts. This section demonstrates various client patterns and connection types.

These examples provide comprehensive patterns for building MCP clients that can handle various server types, authentication methods, and interaction patterns.

## Basic stdio client

Connecting to MCP servers over stdio transport:

```python
--8<-- "examples/snippets/clients/stdio_client.py"
```

This fundamental example demonstrates:

- Creating `StdioServerParameters` for server connection
- Using `ClientSession` for MCP communication
- Listing and calling tools, reading resources, getting prompts
- Handling both structured and unstructured tool results
- Sampling callback implementation for LLM integration

## Streamable HTTP client

Connecting to HTTP-based MCP servers:

```python
--8<-- "examples/snippets/clients/streamable_basic.py"
```

This example shows:

- Using `streamablehttp_client` for HTTP connections
- Simpler connection setup for web-deployed servers
- Basic tool listing and execution over HTTP

## Display utilities

Helper utilities for client user interfaces:

```python
--8<-- "examples/snippets/clients/display_utilities.py"
```

This practical example covers:

- Using `get_display_name()` for human-readable names
- Proper precedence rules for tool/resource titles
- Building user-friendly client interfaces
- Consistent naming across different MCP objects

## OAuth authentication client

Client-side OAuth 2.1 authentication flow:

```python
--8<-- "examples/snippets/clients/oauth_client.py"
```

This comprehensive example demonstrates:

- `OAuthClientProvider` setup and configuration
- Token storage with custom `TokenStorage` implementation
- Authorization flow handling (redirect and callback)
- Authenticated requests to protected MCP servers

## Completion client

Using completion suggestions for better user experience:

```python
--8<-- "examples/snippets/clients/completion_client.py"
```

This advanced example shows:

- Resource template argument completion
- Context-aware completions (e.g., repository suggestions based on owner)
- Prompt argument completion
- Dynamic suggestion generation

## Tool result parsing

Understanding and processing tool results:

```python
--8<-- "examples/snippets/clients/parsing_tool_results.py"
```

This detailed example covers:

- Parsing different content types (`TextContent`, `ImageContent`, `EmbeddedResource`)
- Handling structured output data
- Processing embedded resources
- Error handling for failed tool executions

## Complete chatbot client

A full-featured chatbot that integrates with multiple MCP servers:

```python
--8<-- "examples/clients/simple-chatbot/mcp_simple_chatbot/main.py"
```

This production-ready example includes:

- **Multi-server management**: Connect to multiple MCP servers simultaneously
- **LLM integration**: Use Groq API for natural language processing
- **Tool orchestration**: Automatic tool selection and execution
- **Error handling**: Retry mechanisms and graceful failure handling
- **Configuration management**: JSON-based server configuration
- **Session management**: Persistent conversation context

## Authentication client

Complete OAuth client implementation:

```python
--8<-- "examples/clients/simple-auth-client/mcp_simple_auth_client/main.py"
```

This example demonstrates:

- Full OAuth 2.1 client implementation
- Token management and refresh
- Protected resource access
- Integration with authenticated MCP servers
