"""
Example demonstrating how to create adapters for converting MCP tools to various LLM provider formats.

This example shows:
- Connecting to an MCP server
- Listing available tools
- Converting tools to Gemini, OpenAI, and Claude formats
- Error handling and validation
- Batch conversion utilities

Run from the repository root:
    cd examples/snippets
    uv run llm-adapter-example
"""

import asyncio
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass


class SchemaConversionError(AdapterError):
    """Raised when schema conversion fails."""

    pass


# ============================================================================
# Gemini Adapter
# ============================================================================


def to_gemini_function_declaration(mcp_tool: types.Tool) -> dict[str, Any]:
    """Convert an MCP tool to a Gemini function declaration.

    Args:
        mcp_tool: The MCP tool to convert.

    Returns:
        A dictionary representing a Gemini function declaration.
    """
    schema = mcp_tool.inputSchema
    required_params: list[str] = schema.get("required", [])

    properties: dict[str, Any] = {}
    for key, value in schema.get("properties", {}).items():
        prop_schema = convert_to_gemini_schema(value)
        properties[key] = prop_schema

    function_declaration: dict[str, Any] = {
        "name": mcp_tool.name,
        "description": mcp_tool.description or "",
        "parameters": {
            "type": "OBJECT",
            "properties": properties,
        },
    }

    if required_params:
        function_declaration["parameters"]["required"] = required_params

    return function_declaration


def convert_to_gemini_schema(property_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema property to Gemini schema format.

    Args:
        property_schema: The JSON Schema property definition.

    Returns:
        A dictionary with Gemini-compatible schema fields.
    """
    schema_type = property_schema.get("type", "STRING").upper()

    result: dict[str, Any] = {
        "type": schema_type,
    }

    if "description" in property_schema:
        result["description"] = property_schema["description"]

    # Handle enum values
    if "enum" in property_schema:
        result["enum"] = property_schema["enum"]

    # Handle numeric constraints
    if schema_type in ("INTEGER", "NUMBER"):
        if "minimum" in property_schema:
            result["minimum"] = property_schema["minimum"]
        if "maximum" in property_schema:
            result["maximum"] = property_schema["maximum"]

    # Handle string constraints
    if schema_type == "STRING":
        if "minLength" in property_schema:
            result["minLength"] = property_schema["minLength"]
        if "maxLength" in property_schema:
            result["maxLength"] = property_schema["maxLength"]
        if "pattern" in property_schema:
            result["pattern"] = property_schema["pattern"]

    # Handle arrays
    if schema_type == "ARRAY":
        if "items" in property_schema:
            items_schema = convert_to_gemini_schema(property_schema["items"])
            result["items"] = items_schema
        if "minItems" in property_schema:
            result["minItems"] = property_schema["minItems"]
        if "maxItems" in property_schema:
            result["maxItems"] = property_schema["maxItems"]

    # Handle objects (nested schemas)
    if schema_type == "OBJECT":
        nested_properties: dict[str, Any] = {}
        nested_required: list[str] = []

        for key, value in property_schema.get("properties", {}).items():
            nested_properties[key] = convert_to_gemini_schema(value)
            if key in property_schema.get("required", []):
                nested_required.append(key)

        result["properties"] = nested_properties
        if nested_required:
            result["required"] = nested_required

    return result


# ============================================================================
# OpenAI Adapter
# ============================================================================


def to_openai_function(mcp_tool: types.Tool) -> dict[str, Any]:
    """Convert an MCP tool to an OpenAI function definition.

    Args:
        mcp_tool: The MCP tool to convert.

    Returns:
        A dictionary representing an OpenAI function definition.
    """
    schema = mcp_tool.inputSchema

    # OpenAI uses a slightly different structure
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    # Convert properties
    for key, value in schema.get("properties", {}).items():
        parameters["properties"][key] = convert_to_openai_schema(value)

    # Add required fields
    required = schema.get("required", [])
    if required:
        parameters["required"] = required

    # Build the function definition
    function_def: dict[str, Any] = {
        "name": mcp_tool.name,
        "description": mcp_tool.description or "",
        "parameters": parameters,
    }

    return function_def


def convert_to_openai_schema(property_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema property to OpenAI schema format.

    Args:
        property_schema: The JSON Schema property definition.

    Returns:
        A dictionary with OpenAI-compatible schema fields.
    """
    result: dict[str, Any] = {}

    # Map type
    schema_type = property_schema.get("type", "string")
    if schema_type == "integer":
        result["type"] = "integer"
    elif schema_type == "number":
        result["type"] = "number"
    elif schema_type == "boolean":
        result["type"] = "boolean"
    elif schema_type == "array":
        result["type"] = "array"
        if "items" in property_schema:
            result["items"] = convert_to_openai_schema(property_schema["items"])
    elif schema_type == "object":
        result["type"] = "object"
        nested_properties: dict[str, Any] = {}
        nested_required: list[str] = []

        for key, value in property_schema.get("properties", {}).items():
            nested_properties[key] = convert_to_openai_schema(value)
            if key in property_schema.get("required", []):
                nested_required.append(key)

        result["properties"] = nested_properties
        if nested_required:
            result["required"] = nested_required
    else:
        result["type"] = "string"

    # Add description
    if "description" in property_schema:
        result["description"] = property_schema["description"]

    # Handle enum
    if "enum" in property_schema:
        result["enum"] = property_schema["enum"]

    # Handle numeric constraints
    if schema_type in ("integer", "number"):
        if "minimum" in property_schema:
            result["minimum"] = property_schema["minimum"]
        if "maximum" in property_schema:
            result["maximum"] = property_schema["maximum"]

    # Handle string constraints
    if schema_type == "string":
        if "minLength" in property_schema:
            result["minLength"] = property_schema["minLength"]
        if "maxLength" in property_schema:
            result["maxLength"] = property_schema["maxLength"]
        if "pattern" in property_schema:
            result["pattern"] = property_schema["pattern"]

    # Handle array constraints
    if schema_type == "array":
        if "minItems" in property_schema:
            result["minItems"] = property_schema["minItems"]
        if "maxItems" in property_schema:
            result["maxItems"] = property_schema["maxItems"]

    return result


# ============================================================================
# Anthropic Claude Adapter
# ============================================================================


def to_claude_tool(mcp_tool: types.Tool) -> dict[str, Any]:
    """Convert an MCP tool to an Anthropic Claude tool definition.

    Args:
        mcp_tool: The MCP tool to convert.

    Returns:
        A dictionary representing a Claude tool definition.
    """
    schema = mcp_tool.inputSchema

    # Claude uses a specific structure
    tool_def: dict[str, Any] = {
        "name": mcp_tool.name,
        "description": mcp_tool.description or "",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    }

    # Convert properties
    for key, value in schema.get("properties", {}).items():
        tool_def["input_schema"]["properties"][key] = convert_to_claude_schema(value)

    # Add required fields
    required = schema.get("required", [])
    if required:
        tool_def["input_schema"]["required"] = required

    return tool_def


def convert_to_claude_schema(property_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema property to Claude schema format.

    Args:
        property_schema: The JSON Schema property definition.

    Returns:
        A dictionary with Claude-compatible schema fields.
    """
    result: dict[str, Any] = {}

    # Map type
    schema_type = property_schema.get("type", "string")
    type_mapping = {
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
        "string": "string",
    }
    result["type"] = type_mapping.get(schema_type, "string")

    # Add description
    if "description" in property_schema:
        result["description"] = property_schema["description"]

    # Handle enum
    if "enum" in property_schema:
        result["enum"] = property_schema["enum"]

    # Handle numeric constraints
    if schema_type in ("integer", "number"):
        if "minimum" in property_schema:
            result["minimum"] = property_schema["minimum"]
        if "maximum" in property_schema:
            result["maximum"] = property_schema["maximum"]

    # Handle string constraints
    if schema_type == "string":
        if "minLength" in property_schema:
            result["minLength"] = property_schema["minLength"]
        if "maxLength" in property_schema:
            result["maxLength"] = property_schema["maxLength"]
        if "pattern" in property_schema:
            result["pattern"] = property_schema["pattern"]

    # Handle arrays
    if schema_type == "array":
        if "items" in property_schema:
            result["items"] = convert_to_claude_schema(property_schema["items"])
        if "minItems" in property_schema:
            result["minItems"] = property_schema["minItems"]
        if "maxItems" in property_schema:
            result["maxItems"] = property_schema["maxItems"]

    # Handle objects (nested schemas)
    if schema_type == "object":
        nested_properties: dict[str, Any] = {}
        nested_required: list[str] = []

        for key, value in property_schema.get("properties", {}).items():
            nested_properties[key] = convert_to_claude_schema(value)
            if key in property_schema.get("required", []):
                nested_required.append(key)

        result["properties"] = nested_properties
        if nested_required:
            result["required"] = nested_required

    return result


# ============================================================================
# Utility Functions
# ============================================================================


def validate_tool(mcp_tool: types.Tool) -> None:
    """Validate that an MCP tool has required fields.

    Args:
        mcp_tool: The MCP tool to validate.

    Raises:
        SchemaConversionError: If validation fails.
    """
    if not mcp_tool.name:
        raise SchemaConversionError("Tool name is required")

    if not mcp_tool.inputSchema:
        raise SchemaConversionError("Tool inputSchema is required")

    schema = mcp_tool.inputSchema
    if not isinstance(schema, dict):
        raise SchemaConversionError("inputSchema must be a dictionary")

    if schema.get("type") != "object":
        raise SchemaConversionError("inputSchema type must be 'object'")


def convert_tools_batch(
    mcp_tools: list[types.Tool],
    converter_func: callable[[types.Tool], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Convert multiple MCP tools to provider format.

    Args:
        mcp_tools: List of MCP tools to convert.
        converter_func: Function to convert a single tool.

    Returns:
        Tuple of (converted tools, list of (tool_name, error_message) tuples).
    """
    converted = []
    errors = []

    for tool in mcp_tools:
        try:
            validate_tool(tool)
            converted_tool = converter_func(tool)
            converted.append(converted_tool)
        except Exception as e:
            errors.append((tool.name, str(e)))

    return converted, errors


# ============================================================================
# Main Example
# ============================================================================


async def main() -> None:
    """Main example demonstrating tool conversion."""
    # Create server parameters for stdio connection
    server_params = StdioServerParameters(
        command="uv",  # Using uv to run the server
        args=["run", "server", "fastmcp_quickstart", "stdio"],  # We're already in snippets dir
        env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # List available tools
            tools_response = await session.list_tools()
            mcp_tools = tools_response.tools

            print(f"\n📋 Found {len(mcp_tools)} tools from MCP server:")
            for tool in mcp_tools:
                print(f"  - {tool.name}: {tool.description or 'No description'}")

            # Convert to Gemini format
            print("\n🔷 Converting to Gemini format...")
            gemini_tools, gemini_errors = convert_tools_batch(mcp_tools, to_gemini_function_declaration)
            print(f"  ✅ Converted {len(gemini_tools)} tools successfully")
            if gemini_errors:
                print(f"  ⚠️  {len(gemini_errors)} conversion errors:")
                for tool_name, error in gemini_errors:
                    print(f"     - {tool_name}: {error}")

            # Convert to OpenAI format
            print("\n🔵 Converting to OpenAI format...")
            openai_tools, openai_errors = convert_tools_batch(mcp_tools, to_openai_function)
            print(f"  ✅ Converted {len(openai_tools)} tools successfully")
            if openai_errors:
                print(f"  ⚠️  {len(openai_errors)} conversion errors:")
                for tool_name, error in openai_errors:
                    print(f"     - {tool_name}: {error}")

            # Convert to Claude format
            print("\n🟣 Converting to Claude format...")
            claude_tools, claude_errors = convert_tools_batch(mcp_tools, to_claude_tool)
            print(f"  ✅ Converted {len(claude_tools)} tools successfully")
            if claude_errors:
                print(f"  ⚠️  {len(claude_errors)} conversion errors:")
                for tool_name, error in claude_errors:
                    print(f"     - {tool_name}: {error}")

            # Display example conversions
            if mcp_tools:
                example_tool = mcp_tools[0]
                print(f"\n📝 Example conversion for tool '{example_tool.name}':")
                print("\n  Original MCP tool schema:")
                print(f"    Name: {example_tool.name}")
                print(f"    Description: {example_tool.description or 'N/A'}")
                print(f"    Input Schema: {example_tool.inputSchema}")

                if gemini_tools:
                    print("\n  Gemini format:")
                    import json

                    print(f"    {json.dumps(gemini_tools[0], indent=6)}")

                if openai_tools:
                    print("\n  OpenAI format:")
                    import json

                    print(f"    {json.dumps(openai_tools[0], indent=6)}")

                if claude_tools:
                    print("\n  Claude format:")
                    import json

                    print(f"    {json.dumps(claude_tools[0], indent=6)}")

            print("\n✨ Conversion complete!")
            print("\n💡 Next steps:")
            print("  - Use the converted tools with your LLM provider's API")
            print("  - See docs/llm-adapters.md for more details and best practices")


def run() -> None:
    """Entry point for the script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()

