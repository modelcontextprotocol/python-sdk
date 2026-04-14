import logging
from typing import Any

import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolListChangedNotification,
)


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


@pytest.mark.anyio
async def test_tool_list_changed_notification_clears_schema_cache():
    """ToolListChangedNotification must invalidate the cached output schemas.

    Flow:
      Call 1  — schema v1 (integer). Client caches v1. Result validates OK.
      Call 2  — server switches to v2 (string), sends ToolListChangedNotification
                *before* returning the result, then returns a string value.

    Without the fix the client keeps the stale v1 schema and validates the
    string result against it → RuntimeError (false negative).
    With the fix the notification clears the cache, list_tools() re-fetches v2,
    and the string result validates correctly → no error.
    """
    schema_v1 = {
        "type": "object",
        "properties": {"result": {"type": "integer"}},
        "required": ["result"],
    }
    schema_v2 = {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }

    use_v2: list[bool] = [False]  # mutable container so nested functions can write to it

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        schema = schema_v2 if use_v2[0] else schema_v1
        return ListToolsResult(
            tools=[Tool(name="dynamic_tool", description="d", input_schema={"type": "object"}, output_schema=schema)]
        )

    call_count: list[int] = [0]

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: v1 schema, no notification, integer result.
            return CallToolResult(
                content=[TextContent(type="text", text="r")],
                structured_content={"result": 42},  # valid for v1 (integer)
            )
        # Second call: switch schema to v2, notify BEFORE returning the result,
        # then return a string value that is valid only under v2.
        use_v2[0] = True
        await ctx.session.send_notification(ToolListChangedNotification())
        return CallToolResult(
            content=[TextContent(type="text", text="r")],
            structured_content={"result": "hello"},  # valid for v2 (string), invalid for v1
        )

    server = Server("test-server", on_list_tools=on_list_tools, on_call_tool=on_call_tool)

    async with Client(server) as client:
        # Call 1: populates the cache with v1 schema and succeeds.
        result1 = await client.call_tool("dynamic_tool", {})
        assert result1.structured_content == {"result": 42}

        # Call 2: notification arrives first → (with fix) cache cleared → list_tools()
        # fetches v2 → string "hello" is valid → no error.
        # Without the fix: stale v1 still in cache → "hello" fails integer check → RuntimeError.
        result2 = await client.call_tool("dynamic_tool", {})
        assert result2.structured_content == {"result": "hello"}


@pytest.mark.anyio
async def test_validate_tool_result_paginates_all_pages():
    """_validate_tool_result must paginate through all tool pages when refreshing.

    Without the fix, only the first page of list_tools() is fetched. A tool that
    sits on a later page is never found in the cache, so its output schema is
    silently skipped — invalid structured_content is accepted without error.
    """
    output_schema = {
        "type": "object",
        "properties": {"result": {"type": "integer"}},
        "required": ["result"],
    }

    page1_tools = [
        Tool(name=f"tool_{i}", description="d", input_schema={"type": "object"}) for i in range(3)
    ]
    page2_tools = [
        Tool(
            name="paginated_tool",
            description="d",
            input_schema={"type": "object"},
            output_schema=output_schema,
        )
    ]

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        if params is not None and params.cursor == "page2":
            return ListToolsResult(tools=page2_tools, next_cursor=None)
        return ListToolsResult(tools=page1_tools, next_cursor="page2")

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        # Returns a string for "result" — invalid per the integer schema.
        return CallToolResult(
            content=[TextContent(type="text", text="r")],
            structured_content={"result": "not_an_integer"},
        )

    server = Server("test-server", on_list_tools=on_list_tools, on_call_tool=on_call_tool)

    async with Client(server) as client:
        # With the fix: both pages are fetched, schema is found, invalid content raises.
        # Without the fix: only page 1 is fetched, tool not found, validation silently skipped.
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool paginated_tool"):
            await client.call_tool("paginated_tool", {})
