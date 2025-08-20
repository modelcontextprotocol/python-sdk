# Echo server examples

Echo servers provide a foundation for understanding MCP patterns before building more complex functionality.

Echo servers are useful for:

- **Testing client connections**: Verify that your client can connect and call tools
- **Understanding MCP basics**: Learn the fundamental request/response patterns
- **Development and debugging**: Simple, predictable behavior for testing
- **Protocol verification**: Ensure transport layers work correctly

The following servers are minimal examples that demonstrate basic MCP functionality by echoing input back to clients.

## Simple echo server

The most basic echo implementation:

```python
--8<-- "examples/fastmcp/simple_echo.py"
```

This minimal example shows:

- Single tool implementation with string input/output
- Basic parameter handling
- Simple string manipulation and return

## Enhanced echo server

More sophisticated echo patterns:

```python
--8<-- "examples/fastmcp/echo.py"
```

This enhanced version demonstrates:

- Multiple echo variants (basic echo, uppercase, reverse)
- Different parameter types and patterns
- Tool naming and description best practices

## Usage

These echo servers can be used to test different aspects of MCP:

```bash
# Test with MCP Inspector
uv run mcp dev echo.py

# Test direct execution
python echo.py

# Test with custom clients
# (Use the client examples to connect to these echo servers)
```

## Testing tool calls

Example tool calls you can make to echo servers:

```json
{
  "tool": "echo",
  "arguments": {
    "message": "Hello, MCP!"
  }
}
```

Expected response:

```json
{
  "result": "Echo: Hello, MCP!"
}
```
