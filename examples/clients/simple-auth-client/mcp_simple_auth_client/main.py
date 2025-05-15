"""
Simple OAuth client for the MCP simple-auth server.

This example demonstrates how to use the MCP Python SDK's OAuth client
to connect to an OAuth-protected server.
"""

import asyncio
import json
import logging
import webbrowser

import click
from mcp import ClientSession
from mcp.client.auth import UnauthorizedError
from mcp.client.oauth_providers import FileBasedOAuthProvider, InMemoryOAuthProvider
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientMetadata


class CLIOAuthProvider(InMemoryOAuthProvider):
    """OAuth provider for CLI interactive sessions."""

    def __init__(self, server_url: str):
        client_metadata = OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"],
            client_name="MCP CLI Auth Client",
            scope="user",
        )
        super().__init__(
            redirect_url="http://localhost:8080/callback",
            client_metadata=client_metadata,
        )
        self.server_url = server_url

    async def redirect_to_authorization(self, authorization_url: str) -> None:
        """Open the authorization URL in the browser and prompt for the code."""
        print("\n🔐 Starting OAuth authorization...")
        print(f"Opening browser to: {authorization_url}")

        webbrowser.open(authorization_url)

        print("\nAfter authorizing, copy the 'code' parameter from the callback URL.")
        print("Example: if redirected to 'http://localhost:8080/callback?code=abc123'")
        print("Then paste: abc123")

        auth_code = input("\nPaste the authorization code here: ").strip()
        if auth_code:
            from mcp.client.streamable_http import StreamableHTTPTransport

            transport = StreamableHTTPTransport(
                f"{self.server_url}/mcp",
                auth_provider=self,
            )
            try:
                await transport.finish_auth(auth_code)
                print("✅ Authorization successful!")
            except Exception as e:
                print(f"❌ Authorization failed: {e}")
                raise
        else:
            raise Exception("No authorization code provided")


class InteractiveOAuthProvider(InMemoryOAuthProvider):
    """OAuth provider that handles the authorization flow interactively."""

    async def redirect_to_authorization(self, authorization_url: str) -> None:
        """Open the authorization URL in the browser and prompt for the code."""
        print("\nStarting OAuth authorization flow...")
        print(f"Opening browser to: {authorization_url}")

        # Open the browser
        webbrowser.open(authorization_url)

        print(
            "\nAfter authorizing the application, "
            "you'll be redirected to a callback URL."
        )
        print("Copy the 'code' parameter from the callback URL and paste it here.")
        print(
            "Example: if redirected to "
            "'http://localhost:8080/callback?code=abc123&state=xyz'"
        )
        print("Then copy and paste: abc123")


async def run_oauth_client(
    server_url: str, use_file_storage: bool, debug: bool
) -> None:
    """Run the OAuth client example."""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("mcp").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Create OAuth client metadata
    client_metadata = OAuthClientMetadata(
        redirect_uris=["http://localhost:8080/callback"],
        client_name="Simple MCP Auth Client",
        scope="user",  # Request the 'user' scope for GitHub profile access
    )

    # Choose storage provider
    if use_file_storage:
        print("Using file-based token storage...")
        oauth_provider = FileBasedOAuthProvider(
            redirect_url="http://localhost:8080/callback",
            client_metadata=client_metadata,
        )
    else:
        print("Using in-memory token storage...")
        oauth_provider = InteractiveOAuthProvider(
            redirect_url="http://localhost:8080/callback",
            client_metadata=client_metadata,
        )

    print("Starting OAuth client...")

    try:
        # Check if we have existing tokens
        existing_tokens = await oauth_provider.tokens()
        if existing_tokens:
            print("Found existing tokens. Attempting to connect...")
        else:
            print("No existing tokens found. Will start OAuth flow if needed...")

        # Connect to the MCP server with OAuth
        async with streamablehttp_client(
            f"{server_url}/mcp",
            auth_provider=oauth_provider,
        ) as (read_stream, write_stream, _):
            print("Connecting to MCP server...")

            # Create a session
            async with ClientSession(read_stream, write_stream) as session:
                try:
                    # Initialize the connection (this may trigger OAuth flow)
                    await session.initialize()
                    print("Connected successfully!")

                    # List available tools
                    tools = await session.list_tools()
                    print(f"Available tools: {[tool.name for tool in tools.tools]}")

                    # Call the get_user_profile tool
                    print("Calling get_user_profile tool...")
                    result = await session.call_tool("get_user_profile", {})

                    print("\nGitHub User Profile:")
                    if result.content:
                        # The result content should be a dict in JSON format
                        profile_data = result.content[0].text
                        if isinstance(profile_data, str):
                            # If it's a JSON string, parse it for pretty printing
                            try:
                                parsed_data = json.loads(profile_data)
                                print(json.dumps(parsed_data, indent=2))
                            except json.JSONDecodeError:
                                print(profile_data)
                        else:
                            print(json.dumps(profile_data, indent=2))
                    else:
                        print("No content received")

                except UnauthorizedError:
                    print("\nAuthorization required!")
                    print("Please complete the OAuth flow and run the command again.")

                    # If we're using the interactive provider, we need to manually
                    # handle the callback
                    if isinstance(oauth_provider, InteractiveOAuthProvider):
                        auth_code = input(
                            "\nPaste the authorization code here: "
                        ).strip()
                        if auth_code:
                            # Create a transport to finish the auth
                            from mcp.client.streamable_http import (
                                StreamableHTTPTransport,
                            )

                            transport = StreamableHTTPTransport(
                                f"{server_url}/mcp",
                                auth_provider=oauth_provider,
                            )
                            try:
                                await transport.finish_auth(auth_code)
                                print(
                                    "Authorization successful! "
                                    "Please run the command again."
                                )
                            except Exception as e:
                                print(f"Authorization failed: {e}")
                        else:
                            print("No authorization code provided.")

                except Exception as e:
                    print(f"Error during MCP operations: {e}")
                    if debug:
                        import traceback

                        traceback.print_exc()

    except Exception as e:
        print(f"Failed to connect: {e}")
        if debug:
            import traceback

            traceback.print_exc()

    print("Done!")


async def handle_command(session: ClientSession, command: str) -> None:
    """Handle interactive commands."""
    parts = command.split()
    if not parts:
        return

    cmd = parts[0].lower()

    if cmd == "help":
        print("Available commands:")
        print("  help              - Show this help")
        print("  tools             - List available tools")
        print("  resources         - List available resources")
        print("  prompts           - List available prompts")
        print("  call <tool> [args] - Call a tool")
        print("  read <resource>   - Read a resource")
        print("  exit              - Exit the session")

    elif cmd == "tools":
        tools = await session.list_tools()
        if tools.tools:
            print("Available tools:")
            for tool in tools.tools:
                print(f"  {tool.name}: {tool.description}")
        else:
            print("No tools available")

    elif cmd == "resources":
        resources = await session.list_resources()
        if resources.resources:
            print("Available resources:")
            for resource in resources.resources:
                print(f"  {resource.uri}: {resource.name}")
        else:
            print("No resources available")

    elif cmd == "prompts":
        prompts = await session.list_prompts()
        if prompts.prompts:
            print("Available prompts:")
            for prompt in prompts.prompts:
                print(f"  {prompt.name}: {prompt.description}")
        else:
            print("No prompts available")

    elif cmd == "call" and len(parts) >= 2:
        tool_name = parts[1]
        try:
            # Parse arguments as JSON if provided
            args = {}
            if len(parts) > 2:
                args_str = " ".join(parts[2:])
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    print(f"Invalid JSON arguments: {args_str}")
                    return

            result = await session.call_tool(tool_name, args)
            print(f"Result from {tool_name}:")
            if result.content:
                for content in result.content:
                    if hasattr(content, "text"):
                        print(content.text)
                    else:
                        print(str(content))
            else:
                print("No content received")
        except Exception as e:
            print(f"Error calling tool {tool_name}: {e}")

    elif cmd == "read" and len(parts) >= 2:
        resource_uri = parts[1]
        try:
            result = await session.read_resource(resource_uri)
            print(f"Resource content from {resource_uri}:")
            if result.contents:
                for content in result.contents:
                    if hasattr(content, "text"):
                        print(content.text)
                    else:
                        print(str(content))
            else:
                print("No content received")
        except Exception as e:
            print(f"Error reading resource {resource_uri}: {e}")

    else:
        print(f"Unknown command: {command}")
        print("Type 'help' for available commands")


async def run_interactive_client():
    """Start an interactive MCP client session."""
    server_url = "http://localhost:3000"
    oauth_provider = CLIOAuthProvider(server_url)

    print("🔗 Connecting to localhost:3000...")

    try:
        async with streamablehttp_client(
            f"{server_url}/mcp", auth_provider=oauth_provider
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("✅ Connected!")
                print("Type 'help' for available commands or 'exit' to quit.")

                # Interactive command loop
                while True:
                    try:
                        command = input("mcp> ").strip()
                        if not command or command == "exit":
                            break
                        await handle_command(session, command)
                    except KeyboardInterrupt:
                        break
                    except Exception as e:
                        print(f"Error: {e}")
    except Exception as e:
        print(f"Failed to connect: {e}")

    print("👋 Session ended")


@click.group()
def app():
    """MCP Simple Auth Client CLI"""
    pass


@app.command()
def client():
    """Start an interactive MCP client session."""
    asyncio.run(run_interactive_client())


@app.command()
@click.option(
    "--server-url",
    default="http://localhost:8000",
    help="URL of the MCP server (default: http://localhost:8000)",
)
@click.option(
    "--use-file-storage",
    is_flag=True,
    help="Use file-based token storage instead of in-memory",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def oauth(server_url: str, use_file_storage: bool, debug: bool):
    """Run OAuth client example."""
    asyncio.run(run_oauth_client(server_url, use_file_storage, debug))


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
