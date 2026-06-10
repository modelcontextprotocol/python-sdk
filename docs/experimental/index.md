# Experimental Features

!!! warning "Deprecated"

    The experimental tasks API is deprecated and will be removed in mcp 2.0.
    Tasks (SEP-1686) were removed from the MCP specification and are expected
    to return as a separate MCP extension in a future release.

This section documents experimental features in the MCP Python SDK. These features
are deprecated and remain available on the 1.x line only for existing users.

## Available Experimental Features

### [Tasks](tasks.md)

Tasks enable asynchronous execution of MCP operations. Instead of waiting for a
long-running operation to complete, the server returns a task reference immediately.
Clients can then poll for status updates and retrieve results when ready.

Tasks are useful for:

- **Long-running computations** that would otherwise block
- **Batch operations** that process many items
- **Interactive workflows** that require user input (elicitation) or LLM assistance (sampling)

## Using Experimental APIs

Experimental features are accessed via the `.experimental` property:

```python
# Server-side
@server.experimental.get_task()
async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
    ...

# Client-side
result = await session.experimental.call_tool_as_task("tool_name", {"arg": "value"})
```

Accessing the `.experimental` properties emits a `DeprecationWarning`.

## Providing Feedback

If you rely on these features and have feedback on their deprecation or the planned
MCP extension, please open an issue on the
[python-sdk repository](https://github.com/modelcontextprotocol/python-sdk/issues).
