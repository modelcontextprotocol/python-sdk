import pytest

from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    ClientRequest,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCRequest,
    ListToolsResult,
    Tool,
)


@pytest.mark.anyio
async def test_jsonrpc_request():
    json_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {"batch": None, "sampling": None},
            "clientInfo": {"name": "mcp", "version": "0.1.0"},
        },
    }

    request = JSONRPCMessage.model_validate(json_data)
    assert isinstance(request.root, JSONRPCRequest)
    ClientRequest.model_validate(request.model_dump(by_alias=True, exclude_none=True))

    assert request.root.jsonrpc == "2.0"
    assert request.root.id == 1
    assert request.root.method == "initialize"
    assert request.root.params is not None
    assert request.root.params["protocolVersion"] == LATEST_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_method_initialization():
    """
    Test that the method is automatically set on object creation.
    Testing just for InitializeRequest to keep the test simple, but should be set for other types as well.
    """
    initialize_request = InitializeRequest(
        params=InitializeRequestParams(
            protocolVersion=LATEST_PROTOCOL_VERSION,
            capabilities=ClientCapabilities(),
            clientInfo=Implementation(
                name="mcp",
                version="0.1.0",
            ),
        )
    )

    assert initialize_request.method == "initialize", "method should be set to 'initialize'"
    assert initialize_request.params is not None
    assert initialize_request.params.protocolVersion == LATEST_PROTOCOL_VERSION


def test_tool_preserves_json_schema_2020_12_fields():
    """Verify that JSON Schema 2020-12 keywords are preserved in Tool.inputSchema.

    SEP-1613 establishes JSON Schema 2020-12 as the default dialect for MCP.
    This test ensures the SDK doesn't strip $schema, $defs, or additionalProperties.
    """
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "$defs": {
            "address": {
                "type": "object",
                "properties": {"street": {"type": "string"}, "city": {"type": "string"}},
            }
        },
        "properties": {
            "name": {"type": "string"},
            "address": {"$ref": "#/$defs/address"},
        },
        "additionalProperties": False,
    }

    tool = Tool(name="test_tool", description="A test tool", inputSchema=input_schema)

    # Verify fields are preserved in the model
    assert tool.inputSchema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "$defs" in tool.inputSchema
    assert "address" in tool.inputSchema["$defs"]
    assert tool.inputSchema["additionalProperties"] is False

    # Verify fields survive serialization round-trip
    serialized = tool.model_dump(mode="json", by_alias=True)
    assert serialized["inputSchema"]["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "$defs" in serialized["inputSchema"]
    assert serialized["inputSchema"]["additionalProperties"] is False


def test_list_tools_result_preserves_json_schema_2020_12_fields():
    """Verify JSON Schema 2020-12 fields survive ListToolsResult deserialization."""
    raw_response = {
        "tools": [
            {
                "name": "json_schema_tool",
                "description": "Tool with JSON Schema 2020-12 features",
                "inputSchema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "$defs": {"item": {"type": "string"}},
                    "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/item"}}},
                    "additionalProperties": False,
                },
            }
        ]
    }

    result = ListToolsResult.model_validate(raw_response)
    tool = result.tools[0]

    assert tool.inputSchema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "$defs" in tool.inputSchema
    assert tool.inputSchema["additionalProperties"] is False
