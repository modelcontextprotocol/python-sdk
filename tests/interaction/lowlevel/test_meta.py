"""Request and result _meta round trips against the low-level Server, through the public Client API.

Meta is opaque pass-through data, so these tests assert identity against the value that was sent
rather than snapshotting a literal: the expected value and the sent value are the same variable,
which also proves the SDK injected nothing alongside it.
"""

from typing import Any

import pytest

from mcp import types
from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("meta:request-to-handler")
async def test_request_meta_reaches_handler(connect: Connect) -> None:
    """The _meta object the client attaches to a request arrives at the tool handler unchanged."""
    request_meta = {"example.com/trace": "abc-123"}
    observed_metas: list[dict[str, Any]] = []

    server = Server("observability")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="traced", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "traced"
        ctx = server.request_context
        assert ctx.meta is not None
        observed_metas.append(ctx.meta.model_dump(exclude_none=True))
        return [TextContent(type="text", text="traced")]

    async with connect(server) as client:
        await client.call_tool("traced", {}, meta=request_meta)

    assert observed_metas == [request_meta]


@requirement("meta:result-to-client")
async def test_result_meta_reaches_client(connect: Connect) -> None:
    """The _meta object a handler attaches to its result is delivered to the client unchanged."""
    result_meta = {"example.com/cost": 3}

    server = Server("observability")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="metered", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "metered"
        return CallToolResult(content=[TextContent(type="text", text="done")], _meta=result_meta)

    async with connect(server) as client:
        result = await client.call_tool("metered", {})

    assert result == CallToolResult(content=[TextContent(type="text", text="done")], _meta=result_meta)
