from typing import Annotated

import mcp_types as types
import pytest
from pydantic import Field

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
async def test_field_alias_maps_wire_name_back_to_python_parameter():
    """Regression: a Field(alias=...) publishes the alias in the JSON schema
    but the validated wire input must be forwarded under the Python parameter
    name so the function receives it as a keyword argument it declares."""

    AliasInt = Annotated[int, Field(alias="externalX", ge=1)]

    mcp = MCPServer(name="srv")

    @mcp.tool()
    async def echo(x: AliasInt) -> int:
        return x

    tool_list = list(mcp._tool_manager._tools.values())
    assert len(tool_list) == 1
    schema = tool_list[0].parameters
    assert "externalX" in schema.get("properties", {}), "schema must use alias"
    assert "x" not in schema.get("properties", {}), "schema must not expose Python name"

    async with Client(mcp) as client:
        result = await client.call_tool("echo", {"externalX": 42})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is not True
    assert any(block.text == "42" for block in result.content if hasattr(block, "text"))
