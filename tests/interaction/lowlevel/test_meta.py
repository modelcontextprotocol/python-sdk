"""Request and result _meta round trips against the low-level Server, through the public Client API.

Meta is opaque pass-through, so tests assert identity against the value that was sent: expected
and sent are the same variable, which also proves the SDK injected nothing alongside it.
"""

import mcp_types as types
import pytest
from mcp_types import CallToolResult, RequestParamsMeta, TextContent

from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("meta:request-to-handler")
async def test_request_meta_reaches_handler(connect: Connect) -> None:
    request_meta: RequestParamsMeta = {"example.com/trace": "abc-123"}
    observed_metas: list[dict[str, object]] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="traced", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "traced"
        assert ctx.meta is not None
        observed_metas.append(dict(ctx.meta))
        return CallToolResult(content=[TextContent(text="traced")])

    server = Server("observability", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.call_tool("traced", {}, meta=request_meta)

    assert observed_metas == [dict(request_meta)]


@requirement("meta:result-to-client")
async def test_result_meta_reaches_client(connect: Connect) -> None:
    result_meta = {"example.com/cost": 3}

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="metered", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "metered"
        return CallToolResult(content=[TextContent(text="done")], _meta=result_meta)

    server = Server("observability", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("metered", {})

    assert result == CallToolResult(content=[TextContent(text="done")], _meta=result_meta)
