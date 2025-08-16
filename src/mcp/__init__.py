"""An implementation of the [Model Context Protocol (MCP) specification](https://modelcontextprotocol.io/specification/latest) in Python.

Use the MCP Python SDK to:

- Build MCP clients that can connect to any MCP server
- Build MCP servers that expose resources, prompts, and tools
- Use standard transports like stdio, SSE, and Streamable HTTP
- Handle MCP protocol messages and lifecycle events

## Example - create a [`FastMCP`][mcp.server.fastmcp.FastMCP] server

```python
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    \"\"\"Add two numbers\"\"\"
    return a + b

if __name__ == "__main__":
    mcp.run()
```

## Example - create a client

```python
from mcp import ClientSession, StdioServerParameters, stdio_client

server_params = StdioServerParameters(
    command="python", args=["server.py"]
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("add", {"a": 5, "b": 3})
```

"""

from .client.session import ClientSession
from .client.session_group import ClientSessionGroup
from .client.stdio import StdioServerParameters, stdio_client
from .server.session import ServerSession
from .server.stdio import stdio_server
from .shared.exceptions import McpError
from .types import (
    CallToolRequest,
    ClientCapabilities,
    ClientNotification,
    ClientRequest,
    ClientResult,
    CompleteRequest,
    CreateMessageRequest,
    CreateMessageResult,
    ErrorData,
    GetPromptRequest,
    GetPromptResult,
    Implementation,
    IncludeContext,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsResult,
    LoggingLevel,
    LoggingMessageNotification,
    Notification,
    PingRequest,
    ProgressNotification,
    PromptsCapability,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourcesCapability,
    ResourceUpdatedNotification,
    RootsCapability,
    SamplingMessage,
    ServerCapabilities,
    ServerNotification,
    ServerRequest,
    ServerResult,
    SetLevelRequest,
    StopReason,
    SubscribeRequest,
    Tool,
    ToolsCapability,
    UnsubscribeRequest,
)
from .types import (
    Role as SamplingRole,
)

__all__ = [
    "CallToolRequest",
    "ClientCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResult",
    "ClientSession",
    "ClientSessionGroup",
    "CreateMessageRequest",
    "CreateMessageResult",
    "ErrorData",
    "GetPromptRequest",
    "GetPromptResult",
    "Implementation",
    "IncludeContext",
    "InitializeRequest",
    "InitializeResult",
    "InitializedNotification",
    "JSONRPCError",
    "JSONRPCRequest",
    "ListPromptsRequest",
    "ListPromptsResult",
    "ListResourcesRequest",
    "ListResourcesResult",
    "ListToolsResult",
    "LoggingLevel",
    "LoggingMessageNotification",
    "McpError",
    "Notification",
    "PingRequest",
    "ProgressNotification",
    "PromptsCapability",
    "ReadResourceRequest",
    "ReadResourceResult",
    "ResourcesCapability",
    "ResourceUpdatedNotification",
    "Resource",
    "RootsCapability",
    "SamplingMessage",
    "SamplingRole",
    "ServerCapabilities",
    "ServerNotification",
    "ServerRequest",
    "ServerResult",
    "ServerSession",
    "SetLevelRequest",
    "StdioServerParameters",
    "StopReason",
    "SubscribeRequest",
    "Tool",
    "ToolsCapability",
    "UnsubscribeRequest",
    "stdio_client",
    "stdio_server",
    "CompleteRequest",
    "JSONRPCResponse",
]
