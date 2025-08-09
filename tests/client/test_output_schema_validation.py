import logging
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from mcp.server.lowlevel import Server
from mcp.shared.memory import (
    create_connected_server_and_client_session as client_session,
)
from mcp.types import Tool


@contextmanager
def bypass_server_output_validation():
    """
    Context manager that bypasses server-side output validation.
    This simulates a malicious or non-compliant server that doesn't validate
    its outputs, allowing us to test client-side validation.
    """
    # Patch jsonschema.validate in the server module to disable all validation
    with patch("mcp.server.lowlevel.server.jsonschema.validate"):
        # The mock will simply return None (do nothing) for all validation calls
        yield


class TestClientOutputSchemaValidation:
    """Test client-side validation of structured output from tools"""

    @pytest.mark.anyio
    async def test_tool_structured_output_client_side_validation_basemodel(self):
        """Test that client validates structured content against schema for BaseModel outputs"""
        # Create a malicious low-level server that returns invalid structured content
        server = Server("test-server")

        # Define the expected schema for our tool
        output_schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "title": "Name"}, "age": {"type": "integer", "title": "Age"}},
            "required": ["name", "age"],
            "title": "UserOutput",
        }

        @server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="get_user",
                    description="Get user data",
                    inputSchema={"type": "object"},
                    outputSchema=output_schema,
                )
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            # Return invalid structured content - age is string instead of integer
            # The low-level server will wrap this in CallToolResult
            return {"name": "John", "age": "invalid"}  # Invalid: age should be int

        # Test that client validates the structured content
        with bypass_server_output_validation():
            async with client_session(server) as client:
                # The client validates structured content and should raise an error
                with pytest.raises(RuntimeError) as exc_info:
                    await client.call_tool("get_user", {})
                # Verify it's a validation error
                assert "Invalid structured content returned by tool get_user" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_tool_structured_output_client_side_validation_primitive(self):
        """Test that client validates structured content for primitive outputs"""
        server = Server("test-server")

        # Primitive types are wrapped in {"result": value}
        output_schema = {
            "type": "object",
            "properties": {"result": {"type": "integer", "title": "Result"}},
            "required": ["result"],
            "title": "calculate_Output",
        }

        @server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="calculate",
                    description="Calculate something",
                    inputSchema={"type": "object"},
                    outputSchema=output_schema,
                )
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            # Return invalid structured content - result is string instead of integer
            return {"result": "not_a_number"}  # Invalid: should be int

        with bypass_server_output_validation():
            async with client_session(server) as client:
                # The client validates structured content and should raise an error
                with pytest.raises(RuntimeError) as exc_info:
                    await client.call_tool("calculate", {})
                assert "Invalid structured content returned by tool calculate" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_tool_structured_output_client_side_validation_dict_typed(self):
        """Test that client validates dict[str, T] structured content"""
        server = Server("test-server")

        # dict[str, int] schema
        output_schema = {"type": "object", "additionalProperties": {"type": "integer"}, "title": "get_scores_Output"}

        @server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="get_scores",
                    description="Get scores",
                    inputSchema={"type": "object"},
                    outputSchema=output_schema,
                )
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            # Return invalid structured content - values should be integers
            return {"alice": "100", "bob": "85"}  # Invalid: values should be int

        with bypass_server_output_validation():
            async with client_session(server) as client:
                # The client validates structured content and should raise an error
                with pytest.raises(RuntimeError) as exc_info:
                    await client.call_tool("get_scores", {})
                assert "Invalid structured content returned by tool get_scores" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_tool_structured_output_client_side_validation_missing_required(self):
        """Test that client validates missing required fields"""
        server = Server("test-server")

        output_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}, "email": {"type": "string"}},
            "required": ["name", "age", "email"],  # All fields required
            "title": "PersonOutput",
        }

        @server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="get_person",
                    description="Get person data",
                    inputSchema={"type": "object"},
                    outputSchema=output_schema,
                )
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            # Return structured content missing required field 'email'
            return {"name": "John", "age": 30}  # Missing required 'email'

        with bypass_server_output_validation():
            async with client_session(server) as client:
                # The client validates structured content and should raise an error
                with pytest.raises(RuntimeError) as exc_info:
                    await client.call_tool("get_person", {})
                assert "Invalid structured content returned by tool get_person" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_tool_not_listed_warning(self, caplog: pytest.LogCaptureFixture):
        """Test that client logs warning when tool is not in list_tools but has outputSchema"""
        server = Server("test-server")

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            # Return empty list - tool is not listed
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            # Server still responds to the tool call with structured content
            return {"result": 42}

        # Set logging level to capture warnings
        caplog.set_level(logging.WARNING)

        with bypass_server_output_validation():
            async with client_session(server) as client:
                # Call a tool that wasn't listed
                result = await client.call_tool("mystery_tool", {})
                assert result.structuredContent == {"result": 42}
                assert result.isError is False

                # Check that warning was logged
                assert "Tool mystery_tool not listed" in caplog.text
