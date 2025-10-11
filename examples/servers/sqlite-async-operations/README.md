# SQLite Async Operations Example

This example demonstrates how to implement custom async operations storage and task queuing using SQLite with the MCP Python SDK.

## Architecture

The example showcases the pluggable architecture of the async operations system:

- `SQLiteOperationEventQueue`: Custom event queue that manages operation messages for disconnected clients
- `SQLiteAsyncOperationStore`: Custom implementation that persists operations to SQLite
- `SQLiteAsyncOperationBroker`: Custom implementation that persists pending tasks to SQLite
- `ServerAsyncOperationManager`: Uses both custom store and broker for full persistence
- `FastMCP`: Configured with the custom async operations manager

## Usage

Install and run the server:

```bash
# Using stdio transport (default)
# Run with default SQLite database
uv run mcp-sqlite-async-operations

# Run with custom database path
uv run mcp-sqlite-async-operations --db-path /path/to/custom.db

# Using streamable-http transport on custom port
uv run mcp-sqlite-async-operations --transport streamable-http --port 8000
```

## Testing Persistent Async Operations

1. Start the server
2. Call the async tool (`fetch_data`)
3. **Restart the server while the operation is running**
4. The operation will automatically resume and complete
5. Use the operation token to check status and retrieve results
