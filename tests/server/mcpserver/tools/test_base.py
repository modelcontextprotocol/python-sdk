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
async def test_call_tool_result_create_error_with_image():
    """A tool can return CallToolResult.create_error() with Image helper for non-text error content."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def image_error() -> types.CallToolResult:
        from mcp.server.mcpserver.utilities.types import Image
        img = Image(data=b"fake-png", format="png")
        return types.CallToolResult.create_error(content=[img])

    async with Client(mcp) as client:
        result = await client.call_tool("image_error", {})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], types.ImageContent)


@pytest.mark.anyio
async def test_call_tool_result_create_error_with_audio():
    """A tool can return CallToolResult.create_error() with Audio helper for non-text error content."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def audio_error() -> types.CallToolResult:
        from mcp.server.mcpserver.utilities.types import Audio
        aud = Audio(data=b"fake-wav", format="wav")
        return types.CallToolResult.create_error(content=[aud])

    async with Client(mcp) as client:
        result = await client.call_tool("audio_error", {})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], types.AudioContent)


@pytest.mark.anyio
async def test_call_tool_result_create_error_with_structured_content():
    """A tool can return CallToolResult.create_error() with structured content."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def structured_error() -> types.CallToolResult:
        return types.CallToolResult.create_error(
            content=[types.TextContent(type="text", text="Something went wrong")],
            structured_content={"error_code": "INVALID_INPUT", "details": {"field": "email"}},
        )

    async with Client(mcp) as client:
        result = await client.call_tool("structured_error", {})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True
    assert result.structured_content == {"error_code": "INVALID_INPUT", "details": {"field": "email"}}
