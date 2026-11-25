import logging
from pathlib import Path
from typing import Any

import pytest
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from referencing.exceptions import Unresolvable

from mcp import Client
from mcp.server import Server, ServerRequestContext


def _make_server(
    tools: list[Tool],
    structured_content: dict[str, Any],
) -> Server:
    """Create a low-level server that returns the given structured_content for any tool call."""

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="result")],
            structured_content=structured_content,
        )

    return Server("test-server", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


@pytest.mark.anyio
async def test_tool_structured_output_client_side_validation_basemodel():
    """Test that client validates structured content against schema for BaseModel outputs"""
    output_schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "title": "Name"}, "age": {"type": "integer", "title": "Age"}},
        "required": ["name", "age"],
        "title": "UserOutput",
    }

    server = _make_server(
        tools=[
            Tool(
                name="get_user",
                description="Get user data",
                input_schema={"type": "object"},
                output_schema=output_schema,
            )
        ],
        structured_content={"name": "John", "age": "invalid"},  # Invalid: age should be int
    )

    async with Client(server) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("get_user", {})
        assert "Invalid structured content returned by tool get_user" in str(exc_info.value)


@pytest.mark.anyio
async def test_tool_structured_output_client_side_validation_primitive():
    """Test that client validates structured content for primitive outputs"""
    output_schema = {
        "type": "object",
        "properties": {"result": {"type": "integer", "title": "Result"}},
        "required": ["result"],
        "title": "calculate_Output",
    }

    server = _make_server(
        tools=[
            Tool(
                name="calculate",
                description="Calculate something",
                input_schema={"type": "object"},
                output_schema=output_schema,
            )
        ],
        structured_content={"result": "not_a_number"},  # Invalid: should be int
    )

    async with Client(server) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("calculate", {})
        assert "Invalid structured content returned by tool calculate" in str(exc_info.value)


@pytest.mark.anyio
async def test_tool_structured_output_client_side_validation_dict_typed():
    """Test that client validates dict[str, T] structured content"""
    output_schema = {"type": "object", "additionalProperties": {"type": "integer"}, "title": "get_scores_Output"}

    server = _make_server(
        tools=[
            Tool(
                name="get_scores",
                description="Get scores",
                input_schema={"type": "object"},
                output_schema=output_schema,
            )
        ],
        structured_content={"alice": "100", "bob": "85"},  # Invalid: values should be int
    )

    async with Client(server) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("get_scores", {})
        assert "Invalid structured content returned by tool get_scores" in str(exc_info.value)


@pytest.mark.anyio
async def test_tool_structured_output_client_side_validation_missing_required():
    """Test that client validates missing required fields"""
    output_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}, "email": {"type": "string"}},
        "required": ["name", "age", "email"],
        "title": "PersonOutput",
    }

    server = _make_server(
        tools=[
            Tool(
                name="get_person",
                description="Get person data",
                input_schema={"type": "object"},
                output_schema=output_schema,
            )
        ],
        structured_content={"name": "John", "age": 30},  # Missing required 'email'
    )

    async with Client(server) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("get_person", {})
        assert "Invalid structured content returned by tool get_person" in str(exc_info.value)


@pytest.mark.anyio
async def test_tool_not_listed_warning(caplog: pytest.LogCaptureFixture):
    """Test that client logs warning when tool is not in list_tools but has output_schema"""

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="result")],
            structured_content={"result": 42},
        )

    server = Server("test-server", on_list_tools=on_list_tools, on_call_tool=on_call_tool)

    caplog.set_level(logging.WARNING)

    async with Client(server) as client:
        result = await client.call_tool("mystery_tool", {})
        assert result.structured_content == {"result": 42}
        assert result.is_error is False

        assert "Tool mystery_tool not listed" in caplog.text


# jsonschema's fallback retriever emits this DeprecationWarning; keep it a plain warning so the
# assertions below decide the outcome rather than the suite's warnings-as-errors filter.
@pytest.mark.filterwarnings("default:Automatically retrieving remote references:DeprecationWarning")
@pytest.mark.anyio
async def test_output_schema_ref_outside_the_document_is_rejected(tmp_path: Path):
    """A `$ref` to a URI outside the output schema is not resolved, and a result whose validation
    reaches one fails as an invalid schema (spec `$ref` resolution; applying it to `file:` URIs too
    is SDK-defined)."""
    target = tmp_path / "schema.json"
    target.write_text("{}", encoding="utf-8")
    server = _make_server(
        tools=[Tool(name="probe", input_schema={"type": "object"}, output_schema={"$ref": target.as_uri()})],
        structured_content={"v": 1},
    )

    async with Client(server) as client:
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("probe", {})
    # SDK-authored prefix only; the tail is `referencing`'s text.
    assert str(exc_info.value).startswith("Invalid schema for tool probe: ")
    assert isinstance(exc_info.value.__cause__, Unresolvable)
