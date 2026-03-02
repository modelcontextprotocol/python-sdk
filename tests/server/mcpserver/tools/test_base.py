import pytest

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool


@pytest.mark.anyio
async def test_run_raises_when_context_required_but_not_provided():
    def my_tool(x: int, ctx: Context) -> str:
        raise NotImplementedError

    tool = Tool.from_function(my_tool)
    with pytest.raises(ToolError, match="requires a Context"):
        await tool.run({"x": 1})


@pytest.mark.anyio
async def test_run_succeeds_without_context_when_not_required():
    def my_tool(x: int) -> str:
        return str(x)

    tool = Tool.from_function(my_tool)
    result = await tool.run({"x": 1})
    assert result == "1"


def test_context_detected_in_union_annotation():
    def my_tool(x: int, ctx: Context | None) -> str:
        raise NotImplementedError

    tool = Tool.from_function(my_tool)
    assert tool.context_kwarg == "ctx"
