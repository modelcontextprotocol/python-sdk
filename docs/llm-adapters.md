# LLM Provider Adapters

When integrating MCP tools with various LLM providers, you often need to convert MCP tool schemas to the format required by your target provider. This guide shows you how to create adapter functions for popular LLM providers.

!!! note "Why Adapters?"
    MCP uses a standardized JSON Schema format for tool definitions, but different LLM providers have their own formats. Adapters bridge this gap, allowing you to use MCP tools with any LLM provider.

## Overview

MCP tools are defined using the `mcp.types.Tool` class, which includes:

- `name`: The tool's identifier
- `description`: Human-readable description
- `inputSchema`: JSON Schema defining the tool's parameters
- `outputSchema`: Optional JSON Schema for structured output
- `annotations`: Optional metadata (title, hints, etc.)

The `inputSchema` follows the [JSON Schema specification](https://json-schema.org/), making it straightforward to convert to provider-specific formats.

## Basic Adapter Pattern

All adapters follow a similar pattern:

1. Extract the tool's name, description, and schema
2. Transform the JSON Schema properties to the provider's format
3. Handle required parameters
4. Map type names appropriately
5. Return the provider's tool representation

Here's a simple template:

```python
from mcp.types import Tool

def to_provider_tool(mcp_tool: Tool) -> ProviderToolType:
    """Convert an MCP tool to provider format."""
    # Extract basic information
    name = mcp_tool.name
    description = mcp_tool.description or ""
    
    # Transform the input schema
    schema = mcp_tool.inputSchema
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    
    # Convert properties to provider format
    provider_properties = {}
    for key, value in properties.items():
        provider_properties[key] = convert_property(value, key in required)
    
    # Return provider-specific tool object
    return ProviderToolType(
        name=name,
        description=description,
        parameters=provider_properties,
        required=required,
    )
```

## Google Gemini Adapter

The Google Gemini API uses `FunctionDeclaration` objects with a specific schema format.

### Gemini Basic Implementation

```python
"""Adapter for converting MCP tools to Google Gemini format."""

from typing import Any

from google.genai import types as genai_types
from mcp.types import Tool


def to_gemini_tool(mcp_tool: Tool) -> genai_types.Tool:
    """Convert an MCP tool to a Gemini tool.

    Args:
        mcp_tool: The MCP tool containing name, description, and input schema.

    Returns:
        A Gemini tool with the appropriate function declaration.
    """
    function_declaration = to_gemini_function_declaration(mcp_tool)
    return genai_types.Tool(function_declarations=[function_declaration])


def to_gemini_function_declaration(mcp_tool: Tool) -> genai_types.FunctionDeclarationDict:
    """Convert an MCP tool to a Gemini function declaration.

    Args:
        mcp_tool: The MCP tool to convert.

    Returns:
        A Gemini function declaration dictionary.
    """
    schema = mcp_tool.inputSchema
    required_params: list[str] = schema.get("required", [])
    
    properties: dict[str, Any] = {}
    for key, value in schema.get("properties", {}).items():
        prop_schema = convert_to_gemini_schema(value)
        properties[key] = genai_types.SchemaDict(**prop_schema)
    
    function_declaration = genai_types.FunctionDeclarationDict(
        name=mcp_tool.name,
        description=mcp_tool.description or "",
        parameters=genai_types.SchemaDict(
            type="OBJECT",
            properties=properties,
            required=required_params if required_params else None,
        ),
    )
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
```

### Usage Example

```python
import asyncio

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


async def convert_tools_for_gemini():
    """Example: Convert MCP tools to Gemini format."""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "server", "fastmcp_quickstart", "stdio"],
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List tools from MCP server
            tools_response = await session.list_tools()
            
            # Convert each tool to Gemini format
            gemini_tools = []
            for mcp_tool in tools_response.tools:
                gemini_tool = to_gemini_tool(mcp_tool)
                gemini_tools.append(gemini_tool)
            
            # Now you can use gemini_tools with the Gemini API
            # For example:
            # model = genai.GenerativeModel('gemini-pro', tools=gemini_tools)
            print(f"Converted {len(gemini_tools)} tools to Gemini format")
```

## OpenAI / GPT-4 Adapter

OpenAI's Chat Completions API uses function definitions with a similar but distinct format.

### OpenAI Basic Implementation

```python
"""Adapter for converting MCP tools to OpenAI format."""

from typing import Any

from mcp.types import Tool


def to_openai_function(mcp_tool: Tool) -> dict[str, Any]:
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
```

### OpenAI Usage Example

```python
async def convert_tools_for_openai():
    """Example: Convert MCP tools to OpenAI format."""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "server", "fastmcp_quickstart", "stdio"],
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List tools from MCP server
            tools_response = await session.list_tools()
            
            # Convert each tool to OpenAI format
            openai_functions = []
            for mcp_tool in tools_response.tools:
                function_def = to_openai_function(mcp_tool)
                openai_functions.append(function_def)
            
            # Now you can use openai_functions with the OpenAI API
            # For example:
            # response = openai.ChatCompletion.create(
            #     model="gpt-4",
            #     messages=[...],
            #     functions=openai_functions,
            # )
            print(f"Converted {len(openai_functions)} tools to OpenAI format")
```

## Anthropic Claude Adapter

Anthropic's Claude API uses a structured format for tools that's similar to MCP but with some differences.

### Claude Basic Implementation

```python
"""Adapter for converting MCP tools to Anthropic Claude format."""

from typing import Any

from mcp.types import Tool


def to_claude_tool(mcp_tool: Tool) -> dict[str, Any]:
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
```

### Claude Usage Example

```python
async def convert_tools_for_claude():
    """Example: Convert MCP tools to Claude format."""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "server", "fastmcp_quickstart", "stdio"],
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List tools from MCP server
            tools_response = await session.list_tools()
            
            # Convert each tool to Claude format
            claude_tools = []
            for mcp_tool in tools_response.tools:
                tool_def = to_claude_tool(mcp_tool)
                claude_tools.append(tool_def)
            
            # Now you can use claude_tools with the Anthropic API
            # For example:
            # message = anthropic_client.messages.create(
            #     model="claude-3-opus-20240229",
            #     max_tokens=1024,
            #     tools=claude_tools,
            #     messages=[...],
            # )
            print(f"Converted {len(claude_tools)} tools to Claude format")
```

## Advanced Patterns

### Error Handling

When creating adapters, it's important to handle edge cases and validation errors:

```python
from typing import Any

from mcp.types import Tool


class AdapterError(Exception):
    """Base exception for adapter errors."""
    pass


class SchemaConversionError(AdapterError):
    """Raised when schema conversion fails."""
    pass


def to_provider_tool_safe(mcp_tool: Tool) -> dict[str, Any]:
    """Safely convert an MCP tool with error handling.
    
    Args:
        mcp_tool: The MCP tool to convert.
        
    Returns:
        A dictionary representing the provider tool.
        
    Raises:
        SchemaConversionError: If conversion fails.
    """
    try:
        # Validate tool has required fields
        if not mcp_tool.name:
            raise SchemaConversionError("Tool name is required")
        
        if not mcp_tool.inputSchema:
            raise SchemaConversionError("Tool inputSchema is required")
        
        # Validate schema structure
        schema = mcp_tool.inputSchema
        if not isinstance(schema, dict):
            raise SchemaConversionError("inputSchema must be a dictionary")
        
        if schema.get("type") != "object":
            raise SchemaConversionError("inputSchema type must be 'object'")
        
        # Perform conversion
        return convert_tool(mcp_tool)
        
    except KeyError as e:
        raise SchemaConversionError(f"Missing required field: {e}") from e
    except (TypeError, ValueError) as e:
        raise SchemaConversionError(f"Invalid schema format: {e}") from e
```

### Batch Conversion

For converting multiple tools at once:

```python
from typing import Any

from mcp.types import Tool


def convert_tools_batch(
    mcp_tools: list[Tool],
    converter_func: callable[[Tool], Any],
) -> list[Any]:
    """Convert multiple MCP tools to provider format.
    
    Args:
        mcp_tools: List of MCP tools to convert.
        converter_func: Function to convert a single tool.
        
    Returns:
        List of converted tools.
    """
    converted = []
    errors = []
    
    for tool in mcp_tools:
        try:
            converted_tool = converter_func(tool)
            converted.append(converted_tool)
        except Exception as e:
            errors.append((tool.name, str(e)))
            # Optionally: continue or raise
    
    if errors:
        # Log errors or raise exception
        print(f"Conversion errors: {errors}")
    
    return converted
```

### Preserving Metadata

Some providers support additional metadata. You can preserve MCP tool annotations:

```python
def to_provider_tool_with_metadata(mcp_tool: Tool) -> dict[str, Any]:
    """Convert tool while preserving metadata.
    
    Args:
        mcp_tool: The MCP tool to convert.
        
    Returns:
        Provider tool with metadata preserved.
    """
    tool_def = to_provider_tool(mcp_tool)
    
    # Preserve title if available
    if mcp_tool.annotations and mcp_tool.annotations.title:
        tool_def["title"] = mcp_tool.annotations.title
    
    # Preserve icons if available
    if mcp_tool.icons:
        tool_def["icons"] = [
            {"src": icon.src, "mimeType": icon.mimeType}
            for icon in mcp_tool.icons
        ]
    
    # Preserve custom metadata
    if mcp_tool.meta:
        tool_def["_meta"] = mcp_tool.meta
    
    return tool_def
```

## Best Practices

1. **Validate Input**: Always validate that the MCP tool has required fields before conversion.

2. **Handle Edge Cases**: Consider what happens with:
   - Missing descriptions
   - Empty required arrays
   - Nested objects
   - Array types with complex items
   - Enum values

3. **Type Safety**: Use type hints to make your adapters more maintainable and catch errors early.

4. **Error Messages**: Provide clear error messages when conversion fails, including which tool and field caused the issue.

5. **Test Thoroughly**: Test with various tool schemas:
   - Simple tools (single parameter)
   - Complex tools (nested objects, arrays)
   - Tools with constraints (min/max, patterns)
   - Tools with enums

6. **Document Assumptions**: Document any assumptions your adapter makes about the input schema format.

## Complete Example

See [`examples/snippets/clients/llm_adapter_example.py`](../../examples/snippets/clients/llm_adapter_example.py) for a complete, runnable example that demonstrates:

- Connecting to an MCP server
- Listing available tools
- Converting tools to multiple provider formats
- Error handling and validation
- Batch conversion utilities

## Next Steps

- Review the [MCP Tool specification](https://modelcontextprotocol.io/specification/latest) for complete schema details
- Check your LLM provider's documentation for their exact tool format requirements
- Consider creating reusable adapter libraries for your organization
- Share your adapters with the community!
