"""Tests for client-side validation options."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.client.session import ClientSession, ValidationOptions
from mcp.types import CallToolResult, TextContent


class TestValidationOptions:
    """Test validation options for MCP client sessions."""

    @pytest.mark.anyio
    async def test_strict_validation_default(self):
        """Test that strict validation is enabled by default."""
        # Create a mock client session
        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream)

        # Set up tool with output schema
        client._tool_output_schemas = {
            "test_tool": {
                "type": "object",
                "properties": {"result": {"type": "integer"}},
                "required": ["result"],
            }
        }

        # Mock send_request to return a result without structured content
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="This is unstructured text content")],
            structuredContent=None,
            isError=False,
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should raise by default when structured content is missing
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("test_tool", {})
        assert "has an output schema but did not return structured content" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_lenient_validation_missing_content(self, caplog):
        """Test lenient validation when structured content is missing."""
        # Set logging level to capture warnings
        caplog.set_level(logging.WARNING)

        # Create client with lenient validation
        validation_options = ValidationOptions(strict_output_validation=False)

        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream, validation_options=validation_options)

        # Set up tool with output schema
        client._tool_output_schemas = {
            "test_tool": {
                "type": "object",
                "properties": {"result": {"type": "integer"}},
                "required": ["result"],
            }
        }

        # Mock send_request to return a result without structured content
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="This is unstructured text content")],
            structuredContent=None,
            isError=False,
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should not raise with lenient validation
        result = await client.call_tool("test_tool", {})

        # Should have logged a warning
        assert "has an output schema but did not return structured content" in caplog.text
        assert "Continuing without structured content validation" in caplog.text

        # Result should still be returned
        assert result.isError is False
        assert result.structuredContent is None

    @pytest.mark.anyio
    async def test_lenient_validation_invalid_content(self, caplog):
        """Test lenient validation when structured content is invalid."""
        # Set logging level to capture warnings
        caplog.set_level(logging.WARNING)

        # Create client with lenient validation
        validation_options = ValidationOptions(strict_output_validation=False)

        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream, validation_options=validation_options)

        # Set up tool with output schema
        client._tool_output_schemas = {
            "test_tool": {
                "type": "object",
                "properties": {"result": {"type": "integer"}},
                "required": ["result"],
            }
        }

        # Mock send_request to return a result with invalid structured content
        mock_result = CallToolResult(
            content=[TextContent(type="text", text='{"result": "not_an_integer"}')],
            structuredContent={"result": "not_an_integer"},  # Invalid: string instead of integer
            isError=False,
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should not raise with lenient validation
        result = await client.call_tool("test_tool", {})

        # Should have logged a warning
        assert "Invalid structured content returned by tool test_tool" in caplog.text
        assert "Continuing due to lenient validation mode" in caplog.text

        # Result should still be returned with the invalid content
        assert result.isError is False
        assert result.structuredContent == {"result": "not_an_integer"}

    @pytest.mark.anyio
    async def test_strict_validation_with_valid_content(self):
        """Test that valid structured content passes validation."""
        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream)

        # Set up tool with output schema
        client._tool_output_schemas = {
            "test_tool": {
                "type": "object",
                "properties": {"result": {"type": "integer"}},
                "required": ["result"],
            }
        }

        # Mock send_request to return a result with valid structured content
        mock_result = CallToolResult(
            content=[TextContent(type="text", text='{"result": 42}')], structuredContent={"result": 42}, isError=False
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should not raise with valid content
        result = await client.call_tool("test_tool", {})
        assert result.isError is False
        assert result.structuredContent == {"result": 42}

    @pytest.mark.anyio
    async def test_schema_errors_always_raised(self):
        """Test that schema errors are always raised regardless of validation mode."""
        # Create client with lenient validation
        validation_options = ValidationOptions(strict_output_validation=False)

        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream, validation_options=validation_options)

        # Set up tool with invalid output schema
        client._tool_output_schemas = {
            "test_tool": "not a valid schema"  # type: ignore  # Invalid schema for testing
        }

        # Mock send_request to return a result with structured content
        mock_result = CallToolResult(
            content=[TextContent(type="text", text='{"result": 42}')], structuredContent={"result": 42}, isError=False
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should still raise for schema errors even in lenient mode
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("test_tool", {})
        assert "Invalid schema for tool test_tool" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_error_results_not_validated(self):
        """Test that error results are not validated."""
        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream)

        # Set up tool with output schema
        client._tool_output_schemas = {
            "test_tool": {
                "type": "object",
                "properties": {"result": {"type": "integer"}},
                "required": ["result"],
            }
        }

        # Mock send_request to return an error result
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="Tool execution failed")],
            structuredContent=None,
            isError=True,  # Error result
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should not validate error results
        result = await client.call_tool("test_tool", {})
        assert result.isError is True
        # No exception should be raised

    @pytest.mark.anyio
    async def test_tool_without_output_schema(self):
        """Test that tools without output schema don't trigger validation."""
        read_stream = MagicMock()
        write_stream = MagicMock()

        client = ClientSession(read_stream, write_stream)

        # Tool has no output schema
        client._tool_output_schemas = {"test_tool": None}

        # Mock send_request to return a result without structured content
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="This is unstructured text content")],
            structuredContent=None,
            isError=False,
        )

        client.send_request = AsyncMock(return_value=mock_result)

        # Should not raise when there's no output schema
        result = await client.call_tool("test_tool", {})
        assert result.isError is False
        assert result.structuredContent is None
