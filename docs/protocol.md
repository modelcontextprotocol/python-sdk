# Protocol Features

This page covers cross-cutting MCP protocol features.

## MCP Primitives

The MCP protocol defines three core primitives that servers can implement:

| Primitive | Control               | Description                                         | Example Use                  |
|-----------|-----------------------|-----------------------------------------------------|------------------------------|
| Prompts   | User-controlled       | Interactive templates invoked by user choice        | Slash commands, menu options |
| Resources | Application-controlled| Contextual data managed by the client application   | File contents, API responses |
| Tools     | Model-controlled      | Functions exposed to the LLM to take actions        | API calls, data updates      |

## Server Capabilities

MCP servers declare capabilities during initialization:

| Capability   | Feature Flag                 | Description                        |
|--------------|------------------------------|------------------------------------|
| `prompts`    | `listChanged`                | Prompt template management         |
| `resources`  | `subscribe`<br/>`listChanged`| Resource exposure and updates      |
| `tools`      | `listChanged`                | Tool discovery and execution       |
| `logging`    | -                            | Server logging configuration       |
| `completions`| -                            | Argument completion suggestions    |

## Ping

Both clients and servers can send ping requests to check that the other side is responsive:

```python
# From a client
result = await session.send_ping()

# From a server (via ServerSession)
result = await server_session.send_ping()
```

Both return an `EmptyResult` on success. If the remote side does not respond within the session timeout, an exception is raised.

## Cancellation

Either side can cancel a previously-issued request by sending a `CancelledNotification`:

```python
import mcp.types as types

# Send a cancellation notification
await session.send_notification(
    types.ClientNotification(
        types.CancelledNotification(
            params=types.CancelledNotificationParams(
                requestId="request-id-to-cancel",
                reason="User navigated away",
            )
        )
    )
)
```

The `CancelledNotificationParams` fields:

- `requestId` (optional): The ID of the request to cancel. Required for non-task cancellations.
- `reason` (optional): A human-readable string describing why the request was cancelled.

## Capability Negotiation

During initialization, the client and server exchange capability declarations. The Python SDK automatically declares capabilities based on which callbacks and handlers are registered:

**Client capabilities** (auto-declared when callbacks are provided):

- `sampling` -- declared when `sampling_callback` is passed to `ClientSession`
- `roots` -- declared when `list_roots_callback` is passed to `ClientSession`
- `elicitation` -- declared when `elicitation_callback` is passed to `ClientSession`

**Server capabilities** (auto-declared when handlers are registered):

- `prompts` -- declared when a `list_prompts` handler is registered
- `resources` -- declared when a `list_resources` handler is registered
- `tools` -- declared when a `list_tools` handler is registered
- `logging` -- declared when a `set_logging_level` handler is registered
- `completions` -- declared when a `completion` handler is registered

After initialization, clients can inspect server capabilities:

```python
capabilities = session.get_server_capabilities()
if capabilities and capabilities.tools:
    tools = await session.list_tools()
```

## Protocol Version Negotiation

The SDK defines `LATEST_PROTOCOL_VERSION` and `SUPPORTED_PROTOCOL_VERSIONS` in `mcp.shared.version`:

```python
from mcp.shared.version import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

# LATEST_PROTOCOL_VERSION is the version the SDK advertises during initialization
# SUPPORTED_PROTOCOL_VERSIONS lists all versions the SDK can work with
```

During initialization, the client sends `LATEST_PROTOCOL_VERSION`. If the server responds with a version not in `SUPPORTED_PROTOCOL_VERSIONS`, the client raises a `RuntimeError`. This ensures both sides agree on a compatible protocol version before exchanging messages.

## JSON Schema (2020-12)

MCP uses [JSON Schema 2020-12](https://json-schema.org/draft/2020-12) for tool input schemas, output schemas, and elicitation schemas. When using Pydantic models, schemas are generated automatically via `model_json_schema()`:

```python
from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    query: str = Field(description="Search query string")
    max_results: int = Field(default=10, description="Maximum results to return")


# Pydantic generates a JSON Schema 2020-12 compatible schema:
schema = SearchParams.model_json_schema()
# {
#     "properties": {
#         "query": {"description": "Search query string", "type": "string"},
#         "max_results": {
#             "default": 10,
#             "description": "Maximum results to return",
#             "type": "integer",
#         },
#     },
#     "required": ["query"],
#     "title": "SearchParams",
#     "type": "object",
# }
```

For FastMCP tools, input schemas are derived automatically from function signatures. For structured output, the output schema is derived from the return type annotation.

## Pagination

For pagination details, see:

- Server-side implementation: [Low-Level Server - Pagination](low-level-server.md#pagination-advanced)
- Client-side consumption: [Low-Level Server - Client-side Consumption](low-level-server.md#client-side-consumption)
