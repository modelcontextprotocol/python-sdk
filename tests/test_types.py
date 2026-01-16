from typing import Any

import pytest

from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    ClientRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCRequest,
    ListToolsResult,
    SamplingCapability,
    SamplingMessage,
    TextContent,
    Tool,
    ToolChoice,
    ToolResultContent,
    ToolUseContent,
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


@pytest.mark.anyio
async def test_tool_use_content():
    """Test ToolUseContent type for SEP-1577."""
    tool_use_data = {
        "type": "tool_use",
        "name": "get_weather",
        "id": "call_abc123",
        "input": {"location": "San Francisco", "unit": "celsius"},
    }

    tool_use = ToolUseContent.model_validate(tool_use_data)
    assert tool_use.type == "tool_use"
    assert tool_use.name == "get_weather"
    assert tool_use.id == "call_abc123"
    assert tool_use.input == {"location": "San Francisco", "unit": "celsius"}

    # Test serialization
    serialized = tool_use.model_dump(by_alias=True, exclude_none=True)
    assert serialized["type"] == "tool_use"
    assert serialized["name"] == "get_weather"


@pytest.mark.anyio
async def test_tool_result_content():
    """Test ToolResultContent type for SEP-1577."""
    tool_result_data = {
        "type": "tool_result",
        "toolUseId": "call_abc123",
        "content": [{"type": "text", "text": "It's 72°F in San Francisco"}],
        "isError": False,
    }

    tool_result = ToolResultContent.model_validate(tool_result_data)
    assert tool_result.type == "tool_result"
    assert tool_result.toolUseId == "call_abc123"
    assert len(tool_result.content) == 1
    assert tool_result.isError is False

    # Test with empty content (should default to [])
    minimal_result_data = {"type": "tool_result", "toolUseId": "call_xyz"}
    minimal_result = ToolResultContent.model_validate(minimal_result_data)
    assert minimal_result.content == []


@pytest.mark.anyio
async def test_tool_choice():
    """Test ToolChoice type for SEP-1577."""
    # Test with mode
    tool_choice_data = {"mode": "required"}
    tool_choice = ToolChoice.model_validate(tool_choice_data)
    assert tool_choice.mode == "required"

    # Test with minimal data (all fields optional)
    minimal_choice = ToolChoice.model_validate({})
    assert minimal_choice.mode is None

    # Test different modes
    auto_choice = ToolChoice.model_validate({"mode": "auto"})
    assert auto_choice.mode == "auto"

    none_choice = ToolChoice.model_validate({"mode": "none"})
    assert none_choice.mode == "none"


@pytest.mark.anyio
async def test_sampling_message_with_user_role():
    """Test SamplingMessage with user role for SEP-1577."""
    # Test with single content
    user_msg_data = {"role": "user", "content": {"type": "text", "text": "Hello"}}
    user_msg = SamplingMessage.model_validate(user_msg_data)
    assert user_msg.role == "user"
    assert isinstance(user_msg.content, TextContent)

    # Test with array of content including tool result
    multi_content_data: dict[str, Any] = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Here's the result:"},
            {"type": "tool_result", "toolUseId": "call_123", "content": []},
        ],
    }
    multi_msg = SamplingMessage.model_validate(multi_content_data)
    assert multi_msg.role == "user"
    assert isinstance(multi_msg.content, list)
    assert len(multi_msg.content) == 2


@pytest.mark.anyio
async def test_sampling_message_with_assistant_role():
    """Test SamplingMessage with assistant role for SEP-1577."""
    # Test with tool use content
    assistant_msg_data = {
        "role": "assistant",
        "content": {
            "type": "tool_use",
            "name": "search",
            "id": "call_456",
            "input": {"query": "MCP protocol"},
        },
    }
    assistant_msg = SamplingMessage.model_validate(assistant_msg_data)
    assert assistant_msg.role == "assistant"
    assert isinstance(assistant_msg.content, ToolUseContent)

    # Test with array of mixed content
    multi_content_data: dict[str, Any] = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me search for that..."},
            {"type": "tool_use", "name": "search", "id": "call_789", "input": {}},
        ],
    }
    multi_msg = SamplingMessage.model_validate(multi_content_data)
    assert isinstance(multi_msg.content, list)
    assert len(multi_msg.content) == 2


@pytest.mark.anyio
async def test_sampling_message_backward_compatibility():
    """Test that SamplingMessage maintains backward compatibility."""
    # Old-style message (single content, no tools)
    old_style_data = {"role": "user", "content": {"type": "text", "text": "Hello"}}
    old_msg = SamplingMessage.model_validate(old_style_data)
    assert old_msg.role == "user"
    assert isinstance(old_msg.content, TextContent)

    # New-style message with tool content
    new_style_data: dict[str, Any] = {
        "role": "assistant",
        "content": {"type": "tool_use", "name": "test", "id": "call_1", "input": {}},
    }
    new_msg = SamplingMessage.model_validate(new_style_data)
    assert new_msg.role == "assistant"
    assert isinstance(new_msg.content, ToolUseContent)

    # Array content
    array_style_data: dict[str, Any] = {
        "role": "user",
        "content": [{"type": "text", "text": "Result:"}, {"type": "tool_result", "toolUseId": "call_1", "content": []}],
    }
    array_msg = SamplingMessage.model_validate(array_style_data)
    assert isinstance(array_msg.content, list)


@pytest.mark.anyio
async def test_create_message_request_params_with_tools():
    """Test CreateMessageRequestParams with tools for SEP-1577."""
    tool = Tool(
        name="get_weather",
        description="Get weather information",
        inputSchema={"type": "object", "properties": {"location": {"type": "string"}}},
    )

    params = CreateMessageRequestParams(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text="What's the weather?"))],
        maxTokens=1000,
        tools=[tool],
        toolChoice=ToolChoice(mode="auto"),
    )

    assert params.tools is not None
    assert len(params.tools) == 1
    assert params.tools[0].name == "get_weather"
    assert params.toolChoice is not None
    assert params.toolChoice.mode == "auto"


@pytest.mark.anyio
async def test_create_message_result_with_tool_use():
    """Test CreateMessageResultWithTools with tool use content for SEP-1577."""
    result_data = {
        "role": "assistant",
        "content": {"type": "tool_use", "name": "search", "id": "call_123", "input": {"query": "test"}},
        "model": "claude-3",
        "stopReason": "toolUse",
    }

    # Tool use content uses CreateMessageResultWithTools
    result = CreateMessageResultWithTools.model_validate(result_data)
    assert result.role == "assistant"
    assert isinstance(result.content, ToolUseContent)
    assert result.stopReason == "toolUse"
    assert result.model == "claude-3"

    # Test content_as_list with single content (covers else branch)
    content_list = result.content_as_list
    assert len(content_list) == 1
    assert content_list[0] == result.content


@pytest.mark.anyio
async def test_create_message_result_basic():
    """Test CreateMessageResult with basic text content (backwards compatible)."""
    result_data = {
        "role": "assistant",
        "content": {"type": "text", "text": "Hello!"},
        "model": "claude-3",
        "stopReason": "endTurn",
    }

    # Basic content uses CreateMessageResult (single content, no arrays)
    result = CreateMessageResult.model_validate(result_data)
    assert result.role == "assistant"
    assert isinstance(result.content, TextContent)
    assert result.content.text == "Hello!"
    assert result.stopReason == "endTurn"
    assert result.model == "claude-3"


@pytest.mark.anyio
async def test_client_capabilities_with_sampling_tools():
    """Test ClientCapabilities with nested sampling capabilities for SEP-1577."""
    # New structured format
    capabilities_data: dict[str, Any] = {
        "sampling": {"tools": {}},
    }
    capabilities = ClientCapabilities.model_validate(capabilities_data)
    assert capabilities.sampling is not None
    assert isinstance(capabilities.sampling, SamplingCapability)
    assert capabilities.sampling.tools is not None

    # With both context and tools
    full_capabilities_data: dict[str, Any] = {"sampling": {"context": {}, "tools": {}}}
    full_caps = ClientCapabilities.model_validate(full_capabilities_data)
    assert isinstance(full_caps.sampling, SamplingCapability)
    assert full_caps.sampling.context is not None
    assert full_caps.sampling.tools is not None


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
