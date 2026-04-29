"""Tests for tool annotations in low-level server."""

import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import ListToolsResult, PaginatedRequestParams, Tool, ToolAnnotations


@pytest.mark.anyio
async def test_lowlevel_server_tool_annotations():
    """Test that tool annotations work in low-level server."""

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="echo",
                    description="Echo a message back",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                        },
                        "required": ["message"],
                    },
                    annotations=ToolAnnotations(
                        title="Echo Tool",
                        read_only_hint=True,
                    ),
                )
            ]
        )

    server = Server("test", on_list_tools=handle_list_tools)

    async with Client(server) as client:
        tools_result = await client.list_tools()

        assert len(tools_result.tools) == 1
        assert tools_result.tools[0].name == "echo"
        assert tools_result.tools[0].annotations is not None
        assert tools_result.tools[0].annotations.title == "Echo Tool"
        assert tools_result.tools[0].annotations.read_only_hint is True
