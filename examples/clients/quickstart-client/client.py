# region MCPClient_init
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

    # endregion MCPClient_init

    # region MCPClient_connect_to_server
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

    # endregion MCPClient_connect_to_server

    # region MCPClient_process_query
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

    # endregion MCPClient_process_query

    # region MCPClient_chat_loop
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

    # endregion MCPClient_chat_loop


# region main_entrypoint
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
# endregion main_entrypoint
