"""
Chat CLI - A simple command-line interface for interacting with MCP agents.
"""

import anyio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack

import click
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ElicitRequestParams, ElicitResult, TextContent

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ChatCLI:
    """
    A command-line interface for interacting with MCP agents.
    """

    def __init__(self, servers_config_path: str) -> None:
        """
        Initialize the CLI with configuration for servers it can connect to.

        Args:
            servers_config_path: Path to the servers configuration JSON file
        """
        self.servers_config_path = servers_config_path
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()

    async def load_config(self) -> None:
        """Load the servers configuration from JSON file."""
        with open(self.servers_config_path, "r") as f:
            self.config = json.load(f)

    async def connect(self) -> None:
        """Connect to the configured MCP server."""
        if not hasattr(self, "config"):
            await self.load_config()

        server_config = self.config["mcpServer"]

        try:
            logger.info(f"Connecting to MCP server: {server_config['name']}")

            command = server_config["command"]
            args = server_config.get("args", [])
            env = (
                {**os.environ, **server_config.get("env", {})}
                if server_config.get("env")
                else None
            )

            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env,
            )

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport

            # Register elicitation handler
            async def handle_elicitation(context, params):
                """Handle elicitation requests from the server."""
                return await self.handle_elicitation(params)

            self.session = await self.exit_stack.enter_async_context(
                ClientSession(read, write, elicitation_callback=handle_elicitation)
            )
            await self.session.initialize()

            logger.info(f"Connected to MCP server: {server_config['name']}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise

    async def handle_elicitation(self, params: ElicitRequestParams) -> ElicitResult:
        """
        Handle elicitation requests from the server.

        Args:
            params: The elicitation request parameters

        Returns:
            The elicitation result with user's response
        """
        print(f"\n[Agent is asking]: {params.message}")
        print("Please provide the requested information:")

        # Simple schema handling for demo purposes
        response = {}
        schema = params.requestedSchema

        if schema.get("type") == "object" and "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                prop_type = prop_schema.get("type", "string")
                required = prop_name in schema.get("required", [])

                if prop_type == "boolean":
                    # For boolean, ask for yes/no
                    while True:
                        value = input(f"{prop_name} (yes/no): ").lower()
                        if value in ["yes", "y"]:
                            response[prop_name] = True
                            break
                        elif value in ["no", "n"]:
                            response[prop_name] = False
                            break
                        elif not required:
                            break
                        else:
                            print("Please enter 'yes' or 'no'")

                elif prop_type == "integer":
                    # For integer, parse and validate
                    while True:
                        value = input(f"{prop_name} (number): ")
                        if not value and not required:
                            break
                        try:
                            response[prop_name] = int(value)
                            break
                        except ValueError:
                            print("Please enter a valid number")

                else:  # string or other types default to string
                    while True:
                        value = input(f"{prop_name}: ")
                        if value or not required:
                            if value:
                                response[prop_name] = value
                            break
                        else:
                            print(f"{prop_name} is required")

        return ElicitResult(content=response)

    async def list_tools(self) -> None:
        """List all available tools from the connected server."""
        if not self.session:
            raise RuntimeError("Not connected to any server")

        result = await self.session.list_tools()

        print("\nAvailable tools:")
        for tool in result.tools:
            print(f"\n- {tool.name}: {tool.description}")

            if "properties" in tool.inputSchema:
                print("  Arguments:")
                for arg_name, arg_info in tool.inputSchema["properties"].items():
                    required = arg_name in tool.inputSchema.get("required", [])
                    arg_desc = f"    - {arg_name}: {arg_info.get('description', 'No description')}"
                    if required:
                        arg_desc += " (required)"
                    print(arg_desc)

    async def chat(self) -> None:
        """Start a chat session with the connected server."""
        logger.info("Starting chat session")

        if not self.session:
            raise RuntimeError("Not connected to any server")

        try:
            # Find the chat tool
            result = await self.session.list_tools()
            chat_tool = None

            for tool in result.tools:
                if tool.name == "chat":
                    chat_tool = tool
                    break

            if not chat_tool:
                print("Chat tool not found. Available tools:")
                for tool in result.tools:
                    print(f"- {tool.name}")
                return

            print("\nStarting chat session. Type 'exit' or 'quit' to end.")
            print("Type 'tools' to list available tools.\n")

            while True:
                try:
                    user_input = input("You: ").strip()

                    if user_input.lower() in ["quit", "exit"]:
                        print("Exiting chat...")
                        break

                    if user_input.lower() == "tools":
                        await self.list_tools()
                        continue

                    if not user_input:
                        continue

                    # Call the chat tool
                    result = await self.session.call_tool(
                        "chat", {"message": user_input}
                    )

                    # Extract text content from the result
                    if result.content and isinstance(result.content[0], TextContent):
                        print(f"\nAssistant: {result.content[0].text}")
                    else:
                        print("\nAssistant: [No response]")

                except KeyboardInterrupt:
                    print("\nChat interrupted. Exiting...")
                    break

                except Exception as e:
                    print(f"\nError: {e}")
                    logger.error(f"Error in chat loop: {str(e)}")

        except Exception as e:
            logger.error(f"Error in chat session: {e}")
            print(f"\nAn error occurred: {e}")

    async def cleanup(self) -> None:
        """Clean up resources and close connections."""
        await self.exit_stack.aclose()
        self.session = None


async def _run_chat_cli(servers_config_path: str) -> None:
    """Run the Chat CLI application."""
    cli = ChatCLI(servers_config_path)
    logger.info("Chat CLI started")
    try:
        logger.info("Loading configuration...")
        await cli.load_config()
        await cli.connect()
        logger.info("Configuration loaded successfully")
        await cli.chat()
    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"Error: {e}")
    finally:
        await cli.cleanup()


@click.command()
@click.option("--config", default=None, help="Path to servers configuration JSON file")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
def main(config: str | None, log_level: str) -> int:
    """Run the Chat CLI application."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Use provided config or default
    servers_config_path = config or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "servers_config.json"
    )

    # Run the async part
    anyio.run(_run_chat_cli, servers_config_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
