from collections.abc import Callable
from typing import Annotated

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from pydantic import Field

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import InvalidSignature
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


def array_header(tags: Annotated[list[str], Field(json_schema_extra={"x-mcp-header": "Tags"})]) -> str:
    raise NotImplementedError


def number_header(ratio: Annotated[float, Field(json_schema_extra={"x-mcp-header": "Ratio"})]) -> str:
    raise NotImplementedError


def optional_header(region: Annotated[str | None, Field(json_schema_extra={"x-mcp-header": "Region"})] = None) -> str:
    raise NotImplementedError


def non_token_header(region: Annotated[str, Field(json_schema_extra={"x-mcp-header": "Region Name"})]) -> str:
    raise NotImplementedError


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fn", "message"),
    [
        pytest.param(
            array_header,
            snapshot(
                "Tool 'array_header' has an invalid x-mcp-header annotation: "
                "property 'tags': x-mcp-header is only permitted on integer/string/boolean properties (got 'array')"
            ),
            id="array",
        ),
        pytest.param(
            number_header,
            snapshot(
                "Tool 'number_header' has an invalid x-mcp-header annotation: "
                "property 'ratio': x-mcp-header is only permitted on integer/string/boolean properties (got 'number')"
            ),
            id="number",
        ),
        pytest.param(
            optional_header,
            snapshot(
                "Tool 'optional_header' has an invalid x-mcp-header annotation: "
                "property 'region': x-mcp-header is only permitted on integer/string/boolean properties "
                "(the type keyword is NoneType, not a string)"
            ),
            id="optional",
        ),
        pytest.param(
            non_token_header,
            snapshot(
                "Tool 'non_token_header' has an invalid x-mcp-header annotation: "
                "property 'region': x-mcp-header 'Region Name' is not an RFC 9110 token"
            ),
            id="non-token-name",
        ),
    ],
)
async def test_tool_with_an_invalid_x_mcp_header_annotation_is_rejected_at_registration(
    fn: Callable[..., str], message: str
):
    """SDK-defined: the spec has 2026-07-28 clients exclude such a tool, so registration
    refuses it with an error naming the tool and the reason, and nothing is registered."""
    mcp = MCPServer(name="srv")

    with pytest.raises(InvalidSignature) as exc_info:
        mcp.add_tool(fn)

    assert str(exc_info.value) == message
    assert await mcp.list_tools() == []


@pytest.mark.anyio
async def test_tool_with_valid_x_mcp_header_annotations_is_registered():
    """SDK-defined: string, integer and boolean parameters may carry `x-mcp-header`,
    so a tool that annotates one of each registers."""
    mcp = MCPServer(name="srv")

    @mcp.tool()
    def fetch(
        region: Annotated[str, Field(json_schema_extra={"x-mcp-header": "Region"})],
        shard: Annotated[int, Field(json_schema_extra={"x-mcp-header": "Shard"})],
        dry_run: Annotated[bool, Field(json_schema_extra={"x-mcp-header": "Dry-Run"})],
    ) -> str:
        raise NotImplementedError

    assert [tool.name for tool in await mcp.list_tools()] == ["fetch"]


@pytest.mark.anyio
async def test_tool_reserved_parameter_does_not_collide_with_prefixed_field_name():
    from mcp_types import TextContent

    from mcp import Client
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer(name="srv")

    @mcp.tool()
    def inspect(model_dump: int, field_model_dump: int) -> str:
        return f"seen:{model_dump}:{field_model_dump}"

    @mcp.tool()
    def inspect_reversed(field_model_dump: int, model_dump: int) -> str:
        return f"seen_rev:{field_model_dump}:{model_dump}"

    @mcp.tool()
    def inspect_multiple_collisions(model_dump: int, field_model_dump: int, field_model_dump_1: int) -> str:
        return f"seen_multi:{model_dump}:{field_model_dump}:{field_model_dump_1}"

    @mcp.tool()
    def inspect_argmodel_reserved(model_dump_one_level: int, model_fields: str) -> str:
        return f"seen_reserved:{model_dump_one_level}:{model_fields}"

    tools = await mcp.list_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    assert "model_dump" in tools_by_name["inspect"].input_schema["properties"]
    assert "field_model_dump" in tools_by_name["inspect"].input_schema["properties"]

    assert "model_dump" in tools_by_name["inspect_reversed"].input_schema["properties"]
    assert "field_model_dump" in tools_by_name["inspect_reversed"].input_schema["properties"]

    multi_props = tools_by_name["inspect_multiple_collisions"].input_schema["properties"]
    assert {"model_dump", "field_model_dump", "field_model_dump_1"} <= multi_props.keys()

    reserved_props = tools_by_name["inspect_argmodel_reserved"].input_schema["properties"]
    assert {"model_dump_one_level", "model_fields"} <= reserved_props.keys()

    async with Client(mcp) as client:
        res1 = await client.call_tool(
            "inspect",
            arguments={"model_dump": 1, "field_model_dump": 2},
        )
        assert res1.content == [TextContent(type="text", text="seen:1:2")]

        res2 = await client.call_tool(
            "inspect_reversed",
            arguments={"field_model_dump": 2, "model_dump": 1},
        )
        assert res2.content == [TextContent(type="text", text="seen_rev:2:1")]

        res3 = await client.call_tool(
            "inspect_multiple_collisions",
            arguments={"model_dump": 1, "field_model_dump": 2, "field_model_dump_1": 3},
        )
        assert res3.content == [TextContent(type="text", text="seen_multi:1:2:3")]

        res4 = await client.call_tool(
            "inspect_argmodel_reserved",
            arguments={"model_dump_one_level": 42, "model_fields": "foo"},
        )
        assert res4.content == [TextContent(type="text", text="seen_reserved:42:foo")]
