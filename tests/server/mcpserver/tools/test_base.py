import mcp_types as types
import pytest

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.shared.exceptions import MCPError


def test_context_detected_in_union_annotation():
    def my_tool(x: int, ctx: Context | None) -> str:
        raise NotImplementedError

    tool = Tool.from_function(my_tool)
    assert tool.context_kwarg == "ctx"


@pytest.mark.anyio
async def test_mcperror_raised_from_a_tool_surfaces_as_a_top_level_jsonrpc_error_with_code_and_data_intact():
    """`MCPError` means "respond with a protocol error"; it is not flattened into `CallToolResult(isError=True)`."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def needs_sampling() -> str:
        raise MCPError(
            types.MISSING_REQUIRED_CLIENT_CAPABILITY,
            "sampling capability required",
            data={"requiredCapabilities": ["sampling"]},
        )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("needs_sampling", {})

    assert exc_info.value.error.code == types.MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == {"requiredCapabilities": ["sampling"]}


@pytest.mark.anyio
async def test_non_mcperror_exception_raised_from_a_tool_is_wrapped_as_an_is_error_result():
    """Ordinary exceptions are execution failures the LLM should see, not protocol-level JSON-RPC errors."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def boom() -> str:
        raise RuntimeError("execution failure")

    async with Client(mcp) as client:
        result = await client.call_tool("boom", {})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True
