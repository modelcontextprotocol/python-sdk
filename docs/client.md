# Writing MCP Clients

The SDK provides a high-level client interface for connecting to MCP servers using various [transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):

<!-- snippet-source examples/snippets/clients/stdio_client.py -->
```python
"""
cd to the `examples/snippets/clients` directory and run:
    uv run client
"""

import asyncio
import os

from pydantic import AnyUrl

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.shared.context import RequestContext

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",  # Using uv to run the server
    args=["run", "server", "fastmcp_quickstart", "stdio"],  # We're already in snippets dir
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


# Optional: create a sampling callback
async def handle_sampling_message(
    context: RequestContext[ClientSession, None], params: types.CreateMessageRequestParams
) -> types.CreateMessageResult:
    print(f"Sampling request: {params.messages}")
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text",
            text="Hello, world! from model",
        ),
        model="gpt-3.5-turbo",
        stopReason="endTurn",
    )


async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write, sampling_callback=handle_sampling_message) as session:
            # Initialize the connection
            await session.initialize()

            # List available prompts
            prompts = await session.list_prompts()
            print(f"Available prompts: {[p.name for p in prompts.prompts]}")

            # Get a prompt (greet_user prompt from fastmcp_quickstart)
            if prompts.prompts:
                prompt = await session.get_prompt("greet_user", arguments={"name": "Alice", "style": "friendly"})
                print(f"Prompt result: {prompt.messages[0].content}")

            # List available resources
            resources = await session.list_resources()
            print(f"Available resources: {[r.uri for r in resources.resources]}")

            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")

            # Read a resource (greeting resource from fastmcp_quickstart)
            resource_content = await session.read_resource(AnyUrl("greeting://World"))
            content_block = resource_content.contents[0]
            if isinstance(content_block, types.TextContent):
                print(f"Resource content: {content_block.text}")

            # Call a tool (add tool from fastmcp_quickstart)
            result = await session.call_tool("add", arguments={"a": 5, "b": 3})
            result_unstructured = result.content[0]
            if isinstance(result_unstructured, types.TextContent):
                print(f"Tool result: {result_unstructured.text}")
            result_structured = result.structuredContent
            print(f"Structured tool result: {result_structured}")


def main():
    """Entry point for the client script."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

_Full example: [examples/snippets/clients/stdio_client.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/stdio_client.py)_
<!-- /snippet-source -->

Clients can also connect using [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http):

<!-- snippet-source examples/snippets/clients/streamable_basic.py -->
```python
"""
Run from the repository root:
    uv run examples/snippets/clients/streamable_basic.py
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    # Connect to a streamable HTTP server
    async with streamable_http_client("http://localhost:8000/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        # Create a session using the client streams
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            await session.initialize()
            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[tool.name for tool in tools.tools]}")


if __name__ == "__main__":
    asyncio.run(main())
```

_Full example: [examples/snippets/clients/streamable_basic.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/streamable_basic.py)_
<!-- /snippet-source -->

## Client Display Utilities

When building MCP clients, the SDK provides utilities to help display human-readable names for tools, resources, and prompts:

<!-- snippet-source examples/snippets/clients/display_utilities.py -->
```python
"""
cd to the `examples/snippets` directory and run:
    uv run display-utilities-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.metadata_utils import get_display_name

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",  # Using uv to run the server
    args=["run", "server", "fastmcp_quickstart", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def display_tools(session: ClientSession):
    """Display available tools with human-readable names"""
    tools_response = await session.list_tools()

    for tool in tools_response.tools:
        # get_display_name() returns the title if available, otherwise the name
        display_name = get_display_name(tool)
        print(f"Tool: {display_name}")
        if tool.description:
            print(f"   {tool.description}")


async def display_resources(session: ClientSession):
    """Display available resources with human-readable names"""
    resources_response = await session.list_resources()

    for resource in resources_response.resources:
        display_name = get_display_name(resource)
        print(f"Resource: {display_name} ({resource.uri})")

    templates_response = await session.list_resource_templates()
    for template in templates_response.resourceTemplates:
        display_name = get_display_name(template)
        print(f"Resource Template: {display_name}")


async def run():
    """Run the display utilities example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            print("=== Available Tools ===")
            await display_tools(session)

            print("\n=== Available Resources ===")
            await display_resources(session)


def main():
    """Entry point for the display utilities client."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

_Full example: [examples/snippets/clients/display_utilities.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/display_utilities.py)_
<!-- /snippet-source -->

The `get_display_name()` function implements the proper precedence rules for displaying names:

- For tools: `title` > `annotations.title` > `name`
- For other objects: `title` > `name`

This ensures your client UI shows the most user-friendly names that servers provide.

## OAuth Authentication for Clients

The SDK includes [authorization support](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) for connecting to protected MCP servers:

<!-- snippet-source examples/snippets/clients/oauth_client.py -->
```python
"""
Before running, specify running MCP RS server URL.
To spin up RS server locally, see
    examples/servers/simple-auth/README.md

cd to the `examples/snippets` directory and run:
    uv run oauth-client
"""

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import AnyUrl

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class InMemoryTokenStorage(TokenStorage):
    """Demo In-memory token storage implementation."""

    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        """Get stored tokens."""
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store tokens."""
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Get stored client information."""
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client information."""
        self.client_info = client_info


async def handle_redirect(auth_url: str) -> None:
    print(f"Visit: {auth_url}")


async def handle_callback() -> tuple[str, str | None]:
    callback_url = input("Paste callback URL: ")
    params = parse_qs(urlparse(callback_url).query)
    return params["code"][0], params.get("state", [None])[0]


async def main():
    """Run the OAuth client example."""
    oauth_auth = OAuthClientProvider(
        server_url="http://localhost:8001",
        client_metadata=OAuthClientMetadata(
            client_name="Example MCP Client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="user",
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
    )

    async with httpx.AsyncClient(auth=oauth_auth, follow_redirects=True) as custom_client:
        async with streamable_http_client("http://localhost:8001/mcp", http_client=custom_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                print(f"Available tools: {[tool.name for tool in tools.tools]}")

                resources = await session.list_resources()
                print(f"Available resources: {[r.uri for r in resources.resources]}")


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
```

_Full example: [examples/snippets/clients/oauth_client.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/oauth_client.py)_
<!-- /snippet-source -->

For a complete working example, see [`examples/clients/simple-auth-client/`](../examples/clients/simple-auth-client/).

## Roots

### Listing Roots

Clients can provide a `list_roots_callback` so that servers can discover the client's workspace roots (directories, project folders, etc.):

```python
from typing import Any

from mcp import ClientSession, types
from mcp.shared.context import RequestContext


async def handle_list_roots(
    context: RequestContext[ClientSession, Any],
) -> types.ListRootsResult:
    """Return the client's workspace roots."""
    return types.ListRootsResult(
        roots=[
            types.Root(uri="file:///home/user/project", name="My Project"),
            types.Root(uri="file:///home/user/data", name="Data Folder"),
        ]
    )


# Pass the callback when creating the session
session = ClientSession(
    read_stream,
    write_stream,
    list_roots_callback=handle_list_roots,
)
```

When a `list_roots_callback` is provided, the client automatically declares the `roots` capability (with `listChanged=True`) during initialization.

### Roots Change Notifications

When the client's workspace roots change (e.g., a folder is added or removed), notify the server:

```python
# After roots change, notify the server
await session.send_roots_list_changed()
```

## SSE Transport (Legacy)

For servers that use the older SSE transport, use `sse_client()` from `mcp.client.sse`:

```python
import asyncio

from mcp import ClientSession
from mcp.client.sse import sse_client


async def main():
    async with sse_client("http://localhost:8000/sse") as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")


asyncio.run(main())
```

The `sse_client()` function accepts optional `headers`, `timeout`, `sse_read_timeout`, and `auth` parameters. The SSE transport is considered legacy; prefer [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) for new servers.

## Ping

Send a ping to verify the server is responsive:

```python
# After session.initialize()
result = await session.send_ping()
# Returns EmptyResult on success; raises on timeout
```

## Logging

### Receiving Log Messages

Pass a `logging_callback` to receive log messages from the server:

```python
from mcp import ClientSession, types


async def handle_log(params: types.LoggingMessageNotificationParams) -> None:
    """Handle log messages from the server."""
    print(f"[{params.level}] {params.data}")


session = ClientSession(
    read_stream,
    write_stream,
    logging_callback=handle_log,
)
```

### Setting the Server Log Level

Request that the server change its minimum log level:

```python
await session.set_logging_level("debug")
```

The `level` parameter is a `LoggingLevel` string: `"debug"`, `"info"`, `"notice"`, `"warning"`, `"error"`, `"critical"`, `"alert"`, or `"emergency"`.

## Parsing Tool Results

When calling tools through MCP, the `CallToolResult` object contains the tool's response in a structured format. Understanding how to parse this result is essential for properly handling tool outputs.

```python
"""examples/snippets/clients/parsing_tool_results.py"""

import asyncio

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


async def parse_tool_results():
    """Demonstrates how to parse different types of content in CallToolResult."""
    server_params = StdioServerParameters(
        command="python", args=["path/to/mcp_server.py"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Example 1: Parsing text content
            result = await session.call_tool("get_data", {"format": "text"})
            for content in result.content:
                if isinstance(content, types.TextContent):
                    print(f"Text: {content.text}")

            # Example 2: Parsing structured content from JSON tools
            result = await session.call_tool("get_user", {"id": "123"})
            if hasattr(result, "structuredContent") and result.structuredContent:
                # Access structured data directly
                user_data = result.structuredContent
                print(f"User: {user_data.get('name')}, Age: {user_data.get('age')}")

            # Example 3: Parsing embedded resources
            result = await session.call_tool("read_config", {})
            for content in result.content:
                if isinstance(content, types.EmbeddedResource):
                    resource = content.resource
                    if isinstance(resource, types.TextResourceContents):
                        print(f"Config from {resource.uri}: {resource.text}")
                    elif isinstance(resource, types.BlobResourceContents):
                        print(f"Binary data from {resource.uri}")

            # Example 4: Parsing image content
            result = await session.call_tool("generate_chart", {"data": [1, 2, 3]})
            for content in result.content:
                if isinstance(content, types.ImageContent):
                    print(f"Image ({content.mimeType}): {len(content.data)} bytes")

            # Example 5: Handling errors
            result = await session.call_tool("failing_tool", {})
            if result.isError:
                print("Tool execution failed!")
                for content in result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Error: {content.text}")


async def main():
    await parse_tool_results()


if __name__ == "__main__":
    asyncio.run(main())
```
