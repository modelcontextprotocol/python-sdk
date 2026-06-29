"""Interactive client demonstrating how to handle URL elicitation requests from servers.

Start the elicitation server first (`cd examples/snippets && uv run server elicitation sse`),
then run `uv run elicitation-client` from the same directory.
"""

from __future__ import annotations

import asyncio
import json
import webbrowser
from typing import Any
from urllib.parse import urlparse

import mcp_types as types
from mcp_types import URL_ELICITATION_REQUIRED

from mcp import ClientSession
from mcp.client.context import ClientRequestContext
from mcp.client.sse import sse_client
from mcp.shared.exceptions import MCPError, UrlElicitationRequiredError


async def handle_elicitation(
    context: ClientRequestContext,
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    """Elicitation callback invoked for each server elicitation request; only URL mode is supported here."""
    if params.mode == "url":
        return await handle_url_elicitation(params)
    else:
        return types.ErrorData(
            code=types.INVALID_REQUEST,
            message=f"Unsupported elicitation mode: {params.mode}",
        )


ALLOWED_SCHEMES = {"http", "https"}


async def handle_url_elicitation(
    params: types.ElicitRequestParams,
) -> types.ElicitResult:
    """Show a security warning and open the URL in a browser only with explicit user consent."""
    # url and elicitationId are only present on URL mode requests
    url = getattr(params, "url", None)
    elicitation_id = getattr(params, "elicitationId", None)
    message = params.message

    if not url:
        print("Error: No URL provided in elicitation request")
        return types.ElicitResult(action="cancel")

    # Reject dangerous URL schemes before prompting the user
    parsed = urlparse(str(url))
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        print(f"\nRejecting URL with disallowed scheme '{parsed.scheme}': {url}")
        return types.ElicitResult(action="decline")

    domain = extract_domain(url)

    # Always show the user what they're being asked to open
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

    print(f"\nOpening browser to: {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Failed to open browser: {e}")
        print(f"Please manually open: {url}")

    print("Waiting for you to complete the interaction in your browser...")
    print("(The server will continue once you've finished)")

    return types.ElicitResult(action="accept")


def extract_domain(url: str) -> str:
    """Extract domain from URL for security display."""
    try:
        return urlparse(url).netloc
    except Exception:
        return "unknown"


async def call_tool_with_error_handling(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
) -> types.CallToolResult | None:
    """Call a tool, handling UrlElicitationRequiredError if raised.

    A server tool needing URL elicitation can send an elicitation request directly
    (handled by the elicitation callback) or return error -32042
    (URL_ELICITATION_REQUIRED); this demonstrates catching the error form.
    """
    try:
        result = await session.call_tool(tool_name, arguments)

        if result.is_error:
            print(f"Tool returned error: {result.content}")
            return None

        return result

    except MCPError as e:
        if e.code == URL_ELICITATION_REQUIRED:
            print("\n[Tool requires URL elicitation to proceed]")

            # Convert to typed error to access elicitations
            url_error = UrlElicitationRequiredError.from_error(e.error)

            for elicitation in url_error.elicitations:
                await handle_url_elicitation(elicitation)

            return None
        else:
            print(f"MCP Error: {e.error.message} (code: {e.error.code})")
            return None


def print_help() -> None:
    print("\nAvailable commands:")
    print("  list-tools              - List available tools")
    print("  call <name> [json-args] - Call a tool with optional JSON arguments")
    print("  secure-payment          - Test URL elicitation via ctx.elicit_url()")
    print("  connect-service         - Test URL elicitation via UrlElicitationRequiredError")
    print("  help                    - Show this help")
    print("  quit                    - Exit the program")


def print_tool_result(result: types.CallToolResult | None) -> None:
    if not result:
        return
    print("\nTool result:")
    for content in result.content:
        if isinstance(content, types.TextContent):
            print(f"  {content.text}")
        else:
            print(f"  [{content.type}]")


async def handle_list_tools(session: ClientSession) -> None:
    tools = await session.list_tools()
    if tools.tools:
        print("\nAvailable tools:")
        for tool in tools.tools:
            print(f"  - {tool.name}: {tool.description or 'No description'}")
    else:
        print("No tools available")


async def handle_call_command(session: ClientSession, command: str) -> None:
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
