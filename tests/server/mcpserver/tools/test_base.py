import mcp_types as types
import pytest

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.shared.exceptions import MCPError


def test_context_detected_in_union_annotation():
    def my_tool(x: int, ctx: Context | None) -> str:
        raise NotImplementedError

    tool = Tool.from_function(my_tool)
    assert tool.context_kwarg == "ctx"


@pytest.mark.anyio
async def test_mcperror_raised_from_a_tool_surfaces_as_a_top_level_jsonrpc_error_with_code_and_data_intact():
    """SDK-defined: ``MCPError`` carries JSON-RPC ``ErrorData(code, message, data)``
    and means "respond with a protocol error". The tool wrapper re-raises it so
    the kernel writes a top-level JSON-RPC error - ``code`` and ``data`` survive
    the round-trip rather than being flattened into ``CallToolResult(isError=True)``."""
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
    """SDK-defined: ordinary exceptions from a tool body are execution failures
    the LLM should see, so they become ``CallToolResult(isError=True)`` rather
    than a protocol-level JSON-RPC error. Pins the other arm of the same branch."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def boom() -> str:
        raise RuntimeError("execution failure")

    async with Client(mcp) as client:
        result = await client.call_tool("boom", {})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True


@pytest.mark.anyio
async def test_tool_error_with_content_attaches_that_content_to_the_is_error_result():
    """SDK-defined: a tool can raise ``ToolError(content=...)`` to return a
    ``CallToolResult(isError=True)`` carrying arbitrary content - e.g. an image -
    rather than only the error message as text. The content survives the wrap the
    tool layer applies to exceptions."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def render() -> str:
        raise ToolError(
            "rendering failed",
            content=[types.ImageContent(type="image", data="aGVsbG8=", mime_type="image/png")],
        )

    async with Client(mcp) as client:
        result = await client.call_tool("render", {})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, types.ImageContent)
    assert block.data == "aGVsbG8="
    assert block.mime_type == "image/png"
