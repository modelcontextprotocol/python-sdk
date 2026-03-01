# Quickstart: Build an LLM-powered chatbot

In this tutorial, we'll build an LLM-powered chatbot that connects to an MCP server, discovers its tools, and uses Claude to call them.

Before you begin, it helps to have gone through the [server quickstart](https://modelcontextprotocol.io/quickstart/server) so you understand how clients and servers communicate.

[You can find the complete code for this tutorial here.](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/clients/quickstart-client/)

## Prerequisites

This quickstart assumes you have familiarity with:

- Python
- LLMs like Claude

Before starting, ensure your system meets these requirements:

- Python 3.10 or later installed
- Latest version of `uv` installed
- An Anthropic API key from the [Anthropic Console](https://console.anthropic.com/settings/keys)

## Set up your environment

First, create a new Python project with `uv`:

=== "macOS/Linux"

    ```bash
    # Create project directory
    uv init mcp-client
    cd mcp-client

    # Install required packages
    uv add mcp anthropic

    # Remove boilerplate files
    rm main.py

    # Create our main file
    touch client.py
    ```

=== "Windows"

    ```powershell
    # Create project directory
    uv init mcp-client
    cd mcp-client

    # Install required packages
    uv add mcp anthropic

    # Remove boilerplate files
    del main.py

    # Create our main file
    new-item client.py
    ```

## Creating the client

### Basic client structure

First, let's set up our imports and create the basic client class in `client.py`:

<!-- snippet-source examples/clients/quickstart-client/client.py#MCPClient_init -->
```python
import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock, TextBlockParam, ToolParam, ToolResultBlockParam, ToolUseBlock
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

# Claude model constant
ANTHROPIC_MODEL = "claude-sonnet-4-5"


class MCPClient:
    def __init__(self) -> None:
        # Initialize session and client objects
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self._anthropic: Anthropic | None = None

    @property
    def anthropic(self) -> Anthropic:
        """Lazy-initialize Anthropic client when needed"""
        if self._anthropic is None:
            self._anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return self._anthropic
```
<!-- /snippet-source -->

### Server connection management

Next, we'll implement the method to connect to an MCP server:

<!-- snippet-source examples/clients/quickstart-client/client.py#MCPClient_connect_to_server -->
```python
async def connect_to_server(self, server_script_path: str) -> None:
    """Connect to an MCP server

    Args:
        server_script_path: Path to the server script (.py or .js)
    """
    is_python = server_script_path.endswith(".py")
    is_js = server_script_path.endswith(".js")
    if not (is_python or is_js):
        raise ValueError("Server script must be a .py or .js file")

    if is_python:
        path = Path(server_script_path).resolve()
        server_params = StdioServerParameters(
            command="uv",
            args=["--directory", str(path.parent), "run", path.name],
            env=None,
        )
    else:
        server_params = StdioServerParameters(command="node", args=[server_script_path], env=None)

    stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
    self.stdio, self.write = stdio_transport
    self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

    await self.session.initialize()

    # List available tools
    response = await self.session.list_tools()
    tools = response.tools
    print("\nConnected to server with tools:", [tool.name for tool in tools])
```
<!-- /snippet-source -->

### Query processing logic

Now let's add the core functionality for processing queries and handling tool calls:

<!-- snippet-source examples/clients/quickstart-client/client.py#MCPClient_process_query -->
```python
async def process_query(self, query: str) -> str:
    """Process a query using Claude and available tools"""
    assert self.session is not None
    messages: list[MessageParam] = [{"role": "user", "content": query}]

    response = await self.session.list_tools()
    available_tools: list[ToolParam] = [
        {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema or {}}
        for tool in response.tools
    ]

    # Initial Claude API call
    response = self.anthropic.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=1000, messages=messages, tools=available_tools
    )

    # Process response and handle tool calls
    final_text: list[str] = []

    for content in response.content:
        if isinstance(content, TextBlock):
            final_text.append(content.text)
        elif isinstance(content, ToolUseBlock):
            tool_name = content.name
            tool_args = content.input

            # Execute tool call
            assert self.session is not None
            result = await self.session.call_tool(tool_name, tool_args)
            final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            tool_result_content: list[TextBlockParam] = [
                {"type": "text", "text": block.text} for block in result.content if isinstance(block, TextContent)
            ]
            tool_result: ToolResultBlockParam = {
                "type": "tool_result",
                "tool_use_id": content.id,
                "content": tool_result_content,
            }
            messages.append({"role": "user", "content": [tool_result]})

            # Get next response from Claude
            response = self.anthropic.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1000,
                messages=messages,
            )

            response_text = response.content[0]
            if isinstance(response_text, TextBlock):
                final_text.append(response_text.text)

    return "\n".join(final_text)
```
<!-- /snippet-source -->

### Interactive chat interface

Now we'll add the chat loop and cleanup functionality:

<!-- snippet-source examples/clients/quickstart-client/client.py#MCPClient_chat_loop -->
```python
async def chat_loop(self) -> None:
    """Run an interactive chat loop"""
    print("\nMCP Client Started!")
    print("Type your queries or 'quit' to exit.")

    while True:
        try:
            query = input("\nQuery: ").strip()

            if query.lower() == "quit":
                break

            response = await self.process_query(query)
            print("\n" + response)

        except Exception as e:
            print(f"\nError: {str(e)}")

async def cleanup(self) -> None:
    """Clean up resources"""
    await self.exit_stack.aclose()
```
<!-- /snippet-source -->

### Main entry point

Finally, we'll add the main execution logic:

<!-- snippet-source examples/clients/quickstart-client/client.py#main_entrypoint -->
```python
async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])

        # Check if we have a valid API key to continue
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("\nNo ANTHROPIC_API_KEY found. To query these tools with Claude, set your API key:")
            print("  export ANTHROPIC_API_KEY=your-api-key-here")
            return

        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
```
<!-- /snippet-source -->

## Running the client

To run your client with any MCP server:

=== "macOS/Linux"

    ```bash
    ANTHROPIC_API_KEY=your-key-here uv run client.py path/to/server.py

    # Example: connect to the weather server from the server quickstart
    ANTHROPIC_API_KEY=your-key-here uv run client.py /absolute/path/to/weather/weather.py
    ```

=== "Windows"

    ```powershell
    $env:ANTHROPIC_API_KEY="your-key-here"; uv run client.py path\to\server.py
    ```

The client will:

1. Connect to the specified server
2. List available tools
3. Start an interactive chat session where you can:
   - Enter queries
   - See tool executions
   - Get responses from Claude

## What's happening under the hood

When you submit a query:

1. Your query is sent to Claude along with the tool descriptions discovered during connection
2. Claude decides which tools (if any) to use
3. The client executes any requested tool calls through the server
4. Results are sent back to Claude
5. Claude provides a natural language response
6. The response is displayed to you

## Troubleshooting

### Server path issues

- Double-check the path to your server script is correct
- Use the absolute path if the relative path isn't working
- For Windows users, make sure to use forward slashes (`/`) or escaped backslashes (`\\`) in the path
- Verify the server file has the correct extension (`.py` for Python or `.js` for Node.js)

Example of correct path usage:

=== "macOS/Linux"

    ```bash
    # Relative path
    uv run client.py ./server/weather.py

    # Absolute path
    uv run client.py /Users/username/projects/mcp-server/weather.py
    ```

=== "Windows"

    ```powershell
    # Relative path
    uv run client.py .\server\weather.py

    # Absolute path (either format works)
    uv run client.py C:\projects\mcp-server\weather.py
    uv run client.py C:/projects/mcp-server/weather.py
    ```

### Response timing

- The first response might take up to 30 seconds to return
- This is normal and happens while:
  - The server initializes
  - Claude processes the query
  - Tools are being executed
- Subsequent responses are typically faster
- Don't interrupt the process during this initial waiting period

### Common error messages

If you see:

- `FileNotFoundError`: Check your server script path
- `ModuleNotFoundError: No module named 'mcp'`: Make sure you ran `uv add mcp anthropic` in your project
- `ValueError: Server script must be a .py or .js file`: The client only supports Python and Node.js servers
- `anthropic.AuthenticationError`: Check that your `ANTHROPIC_API_KEY` is valid

## Next steps

- **[Example servers](https://modelcontextprotocol.io/examples)** — Browse official MCP servers and implementations
- **[Example clients](https://modelcontextprotocol.io/clients)** — View clients that support MCP integrations
