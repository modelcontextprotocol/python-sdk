"""URL Elicitation Client Example.

Demonstrates how clients handle URL elicitation requests from servers.
This is the Python equivalent of TypeScript SDK's elicitationUrlExample.ts,
focused on URL elicitation patterns without OAuth complexity.

Features demonstrated:
1. Client elicitation capability declaration
2. Handling elicitation requests from servers via callback
3. Catching UrlElicitationRequiredError from tool calls
4. Browser interaction with security warnings
5. Interactive CLI for testing

Run with:
    cd examples/snippets
    uv run elicitation-client

Requires a server with URL elicitation tools running. Start the elicitation
server first:
    uv run server elicitation sse
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import webbrowser
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError, UrlElicitationRequiredError
from mcp.types import URL_ELICITATION_REQUIRED


async def handle_elicitation(
    context: RequestContext[ClientSession, Any],
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    """Handle elicitation requests from the server.

    This callback is invoked when the server sends an elicitation/request.
    For URL mode, we prompt the user and optionally open their browser.
    """
    if params.mode == "url":
        return await handle_url_elicitation(params)
    else:
        # We only support URL mode in this example
        return types.ErrorData(
            code=types.INVALID_REQUEST,
            message=f"Unsupported elicitation mode: {params.mode}",
        )


async def handle_url_elicitation(
    params: types.ElicitRequestParams,
) -> types.ElicitResult:
    """Handle URL mode elicitation - show security warning and optionally open browser.

    This function demonstrates the security-conscious approach to URL elicitation:
    1. Display the full URL and domain for user inspection
    2. Show the server's reason for requesting this interaction
    3. Require explicit user consent before opening any URL
    """
    # Extract URL parameters - these are available on URL mode requests
    url = getattr(params, "url", None)
    elicitation_id = getattr(params, "elicitationId", None)
    message = params.message

    if not url:
        print("Error: No URL provided in elicitation request")
        return types.ElicitResult(action="cancel")

    # Extract domain for security display
    domain = extract_domain(url)

    # Security warning - always show the user what they're being asked to do
    print("\n" + "=" * 60)
    print("SECURITY WARNING: External URL Request")
    print("=" * 60)
    print("\nThe server is requesting you to open an external URL.")
    print(f"\n  Domain:  {domain}")
    print(f"  Full URL: {url}")
    print("\n  Server's reason:")
    print(f"    {message}")
    print(f"\n  Elicitation ID: {elicitation_id}")
    print("\n" + "-" * 60)

    # Get explicit user consent
    try:
        response = input("\nOpen this URL in your browser? (y/n): ").strip().lower()
    except EOFError:
        return types.ElicitResult(action="cancel")

    if response in ("n", "no"):
        print("URL navigation declined.")
        return types.ElicitResult(action="decline")
    elif response not in ("y", "yes"):
        print("Invalid response. Cancelling.")
        return types.ElicitResult(action="cancel")

    # Open the browser
    print(f"\nOpening browser to: {url}")
    open_browser(url)

    print("Waiting for you to complete the interaction in your browser...")
    print("(The server will continue once you've finished)")

    return types.ElicitResult(action="accept")


def extract_domain(url: str) -> str:
    """Extract domain from URL for security display."""
    try:
        return urlparse(url).netloc
    except Exception:
        return "unknown"


def open_browser(url: str) -> None:
    """Open URL in the default browser."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        elif sys.platform == "win32":
            subprocess.run(["start", url], shell=True, check=False)
        else:
            webbrowser.open(url)
    except Exception as e:
        print(f"Failed to open browser: {e}")
        print(f"Please manually open: {url}")


async def call_tool_with_error_handling(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
) -> types.CallToolResult | None:
    """Call a tool, handling UrlElicitationRequiredError if raised.

    When a server tool needs URL elicitation before it can proceed,
    it can either:
    1. Send an elicitation request directly (handled by elicitation_callback)
    2. Return an error with code -32042 (URL_ELICITATION_REQUIRED)

    This function demonstrates handling case 2 - catching the error
    and processing the required URL elicitations.
    """
    try:
        result = await session.call_tool(tool_name, arguments)

        # Check if the tool returned an error in the result
        if result.isError:
            print(f"Tool returned error: {result.content}")
            return None

        return result

    except McpError as e:
        # Check if this is a URL elicitation required error
        if e.error.code == URL_ELICITATION_REQUIRED:
            print("\n[Tool requires URL elicitation to proceed]")

            # Convert to typed error to access elicitations
            url_error = UrlElicitationRequiredError.from_error(e.error)

            # Process each required elicitation
            for elicitation in url_error.elicitations:
                await handle_url_elicitation(elicitation)

            return None
        else:
            # Re-raise other MCP errors
            print(f"MCP Error: {e.error.message} (code: {e.error.code})")
            return None


def print_help() -> None:
    """Print available commands."""
    print("\nAvailable commands:")
    print("  list-tools              - List available tools")
    print("  call <name> [json-args] - Call a tool with optional JSON arguments")
    print("  secure-payment          - Test URL elicitation via ctx.elicit_url()")
    print("  connect-service         - Test URL elicitation via UrlElicitationRequiredError")
    print("  help                    - Show this help")
    print("  quit                    - Exit the program")


def print_tool_result(result: types.CallToolResult | None) -> None:
    """Print a tool call result."""
    if not result:
        return
    print("\nTool result:")
    for content in result.content:
        if isinstance(content, types.TextContent):
            print(f"  {content.text}")
        else:
            print(f"  [{content.type}]")


async def handle_list_tools(session: ClientSession) -> None:
    """Handle the list-tools command."""
    tools = await session.list_tools()
    if tools.tools:
        print("\nAvailable tools:")
        for tool in tools.tools:
            print(f"  - {tool.name}: {tool.description or 'No description'}")
    else:
        print("No tools available")


async def handle_call_command(session: ClientSession, command: str) -> None:
    """Handle the call command."""
    parts = command.split(maxsplit=2)
    if len(parts) < 2:
        print("Usage: call <tool-name> [json-args]")
        return

    tool_name = parts[1]
    args: dict[str, Any] = {}
    if len(parts) > 2:
        try:
            args = json.loads(parts[2])
        except json.JSONDecodeError as e:
            print(f"Invalid JSON arguments: {e}")
            return

    print(f"\nCalling tool '{tool_name}' with args: {args}")
    result = await call_tool_with_error_handling(session, tool_name, args)
    print_tool_result(result)


async def process_command(session: ClientSession, command: str) -> bool:
    """Process a single command. Returns False if should exit."""
    if command in {"quit", "exit"}:
        print("Goodbye!")
        return False

    if command == "help":
        print_help()
    elif command == "list-tools":
        await handle_list_tools(session)
    elif command.startswith("call "):
        await handle_call_command(session, command)
    elif command == "secure-payment":
        print("\nTesting secure_payment tool (uses ctx.elicit_url())...")
        result = await call_tool_with_error_handling(session, "secure_payment", {"amount": 99.99})
        print_tool_result(result)
    elif command == "connect-service":
        print("\nTesting connect_service tool (raises UrlElicitationRequiredError)...")
        result = await call_tool_with_error_handling(session, "connect_service", {"service_name": "github"})
        print_tool_result(result)
    else:
        print(f"Unknown command: {command}")
        print("Type 'help' for available commands.")

    return True


async def run_command_loop(session: ClientSession) -> None:
    """Run the interactive command loop."""
    while True:
        try:
            command = input("> ").strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n")
            break

        if not command:
            continue

        if not await process_command(session, command):
            break


async def main() -> None:
    """Run the interactive URL elicitation client."""
    server_url = "http://localhost:8000/sse"

    print("=" * 60)
    print("URL Elicitation Client Example")
    print("=" * 60)
    print(f"\nConnecting to: {server_url}")
    print("(Start server with: cd examples/snippets && uv run server elicitation sse)")

    try:
        async with sse_client(server_url) as (read, write):
            async with ClientSession(
                read,
                write,
                elicitation_callback=handle_elicitation,
            ) as session:
                await session.initialize()
                print("\nConnected! Type 'help' for available commands.\n")
                await run_command_loop(session)

    except ConnectionRefusedError:
        print(f"\nError: Could not connect to {server_url}")
        print("Make sure the elicitation server is running:")
        print("  cd examples/snippets && uv run server elicitation sse")
    except Exception as e:
        print(f"\nError: {e}")
        raise


def run() -> None:
    """Entry point for the client script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
