from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools.base import Tool


def test_context_detected_in_union_annotation():
    def my_tool(x: int, ctx: Context | None) -> str:
        raise NotImplementedError

    tool = Tool.from_function(my_tool)
    assert tool.context_kwarg == "ctx"
