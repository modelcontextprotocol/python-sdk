# Experimental Features

!!! warning "Experimental APIs"

    The features in this section are experimental and may change without notice.
    They track the evolving MCP specification and are not yet stable.

This section documents experimental features in the MCP Python SDK. These features
implement draft specifications that are still being refined.

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

## Providing Feedback

Since these features are experimental, feedback is especially valuable. If you encounter
issues or have suggestions, please open an issue on the
[python-sdk repository](https://github.com/modelcontextprotocol/python-sdk/issues).
