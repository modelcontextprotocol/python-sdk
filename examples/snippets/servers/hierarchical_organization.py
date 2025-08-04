"""Example demonstrating hierarchical organization of tools, prompts, and resources using custom URIs.

This example shows how to:
1. Register tools, prompts, and resources with hierarchical URIs
2. Create group discovery resources at well-known URIs
3. Filter items by URI paths for better organization
"""

import json
from typing import cast

from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.types import ListFilters, TextContent, TextResourceContents

# Create FastMCP server instance
mcp = FastMCP("hierarchical-example")


# Group discovery resources
@mcp.resource("mcp://groups/tools")
def get_tool_groups() -> str:
    """Discover available tool groups."""
    return json.dumps(
        {
            "groups": [
                {"name": "math", "description": "Mathematical operations", "uri_paths": ["mcp://tools/math/"]},
                {"name": "string", "description": "String manipulation", "uri_paths": ["mcp://tools/string/"]},
            ]
        },
        indent=2,
    )


@mcp.resource("mcp://groups/prompts")
def get_prompt_groups() -> str:
    """Discover available prompt groups."""
    return json.dumps(
        {
            "groups": [
                {"name": "greetings", "description": "Greeting prompts", "uri_paths": ["mcp://prompts/greetings/"]},
                {
                    "name": "instructions",
                    "description": "Instructional prompts",
                    "uri_paths": ["mcp://prompts/instructions/"],
                },
            ]
        },
        indent=2,
    )


# Math tools organized under mcp://tools/math/
@mcp.tool(uri="mcp://tools/math/add")
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@mcp.tool(uri="mcp://tools/math/multiply")
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


# String tools organized under mcp://tools/string/
@mcp.tool(uri="mcp://tools/string/reverse")
def reverse(text: str) -> str:
    """Reverse a string."""
    return text[::-1]


@mcp.tool(uri="mcp://tools/string/upper")
def upper(text: str) -> str:
    """Convert to uppercase."""
    return text.upper()


# Greeting prompts organized under mcp://prompts/greetings/
@mcp.prompt(uri="mcp://prompts/greetings/hello")
def hello_prompt(name: str) -> str:
    """Generate a hello greeting."""
    return f"Hello, {name}! How can I help you today?"


@mcp.prompt(uri="mcp://prompts/greetings/goodbye")
def goodbye_prompt(name: str) -> str:
    """Generate a goodbye message."""
    return f"Goodbye, {name}! Have a great day!"


# Instruction prompts organized under mcp://prompts/instructions/
@mcp.prompt(uri="mcp://prompts/instructions/setup")
def setup_prompt(tool: str) -> str:
    """Generate setup instructions for a tool."""
    return (
        f"To set up {tool}, follow these steps:\n"
        "1. Install the required dependencies\n"
        "2. Configure the settings\n"
        "3. Run the initialization script\n"
        "4. Verify the installation"
    )


@mcp.prompt(uri="mcp://prompts/instructions/debug")
def debug_prompt(error: str) -> str:
    """Generate debugging instructions for an error."""
    return (
        f"To debug '{error}':\n"
        "1. Check the error logs\n"
        "2. Verify input parameters\n"
        "3. Enable verbose logging\n"
        "4. Isolate the issue with minimal reproduction"
    )


if __name__ == "__main__":
    # Example of testing the hierarchical organization
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session

    async def test_hierarchy():
        """Test the hierarchical organization."""
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            # 1. Discover tool groups and list tools in each group
            print("\n=== Discovering Tool Groups ===")
            result = await client.read_resource(uri=AnyUrl("mcp://groups/tools"))
            tool_groups = json.loads(cast(TextResourceContents, result.contents[0]).text)

            for group in tool_groups["groups"]:
                print(f"\n--- {group['name'].upper()} Tools ({group['description']}) ---")
                # Use the URI paths from the group definition
                group_tools = await client.list_tools(
                    filters=ListFilters(uri_paths=[AnyUrl(uri) for uri in group["uri_paths"]])
                )
                for tool in group_tools.tools:
                    print(f"  - {tool.name}: {tool.description}")

            # 2. Call tools by name (still works!)
            print("\n=== Calling Tools by Name ===")
            result = await client.call_tool("add", {"a": 10, "b": 5})
            print(f"add(10, 5) = {cast(TextContent, result.content[0]).text}")

            result = await client.call_tool("reverse", {"text": "Hello"})
            print(f"reverse('Hello') = {cast(TextContent, result.content[0]).text}")

            # 3. Call tools by URI
            print("\n=== Calling Tools by URI ===")
            result = await client.call_tool("mcp://tools/math/multiply", {"a": 7, "b": 8})
            print(
                f"Call mcp://tools/math/multiply with {{'a': 7, 'b': 8}} = {cast(TextContent, result.content[0]).text}"
            )

            result = await client.call_tool("mcp://tools/string/upper", {"text": "hello world"})
            print(
                f"Call mcp://tools/string/upper with {{'text': 'hello world'}} = "
                f"{cast(TextContent, result.content[0]).text}"
            )

            # 4. Discover prompt groups and list prompts in each group
            print("\n=== Discovering Prompt Groups ===")
            result = await client.read_resource(uri=AnyUrl("mcp://groups/prompts"))
            prompt_groups = json.loads(cast(TextResourceContents, result.contents[0]).text)

            for group in prompt_groups["groups"]:
                print(f"\n--- {group['name'].upper()} Prompts ({group['description']}) ---")
                # Use the URI paths from the group definition
                group_prompts = await client.list_prompts(
                    filters=ListFilters(uri_paths=[AnyUrl(uri) for uri in group["uri_paths"]])
                )
                for prompt in group_prompts.prompts:
                    print(f"  - {prompt.name}: {prompt.description}")

            # 5. Use a prompt
            print("\n=== Using a Prompt ===")
            result = await client.get_prompt("hello_prompt", {"name": "Alice"})
            print(f"Prompt result: {cast(TextContent, result.messages[0].content).text}")

    # Run the test
    asyncio.run(test_hierarchy())
