"""Transport-level composed flows: multi-client isolation, reconnection, and dual-transport hosting.

These scenarios span multiple connections or transports, so they connect real `Client`s against
one mounted server rather than running over the matrix.
"""

import anyio
import httpx
import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, LoggingMessageNotificationParams, TextContent

from mcp.client.session import LoggingFnT
from mcp.server.mcpserver import Context, MCPServer
from tests.interaction._connect import client_via_http, connect_over_sse, mounted_app
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("flow:multi-client:stateful-isolation")
async def test_concurrent_clients_on_one_stateful_server_receive_only_their_own_notifications() -> None:
    """Complements `test_terminating_one_session_leaves_others_working` with the notification-isolation dimension."""
    mcp = MCPServer("multi")

    @mcp.tool()
    async def announce(label: str, ctx: Context) -> str:
        """Emit one info-level log carrying the caller's label, then return it."""
        await ctx.info(label)  # pyright: ignore[reportDeprecated]
        return label

    received_a: list[object] = []
    received_b: list[object] = []

    async def collect_a(params: LoggingMessageNotificationParams) -> None:
        received_a.append(params.data)

    async def collect_b(params: LoggingMessageNotificationParams) -> None:
        received_b.append(params.data)

    async with mounted_app(mcp) as (http, _):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call(label: str, collect: LoggingFnT) -> None:
                    async with client_via_http(http, logging_callback=collect) as client:
                        await client.call_tool("announce", {"label": label})

                tg.start_soon(call, "a", collect_a)
                tg.start_soon(call, "b", collect_b)

    assert received_a == ["a"]
    assert received_b == ["b"]


@requirement("flow:session:terminate-then-reconnect")
async def test_a_fresh_connection_after_termination_obtains_a_new_session_and_operates() -> None:
    """Exiting the first client's context fires its session DELETE; the second connection gets a distinct session."""
    mcp = MCPServer("reconnectable")

    @mcp.tool()
    def echo(text: str) -> str:
        """Return the input unchanged."""
        return text

    session_ids: list[str] = []

    async def record(request: httpx.Request) -> None:
        session_id = request.headers.get("mcp-session-id")
        if session_id is not None:
            session_ids.append(session_id)

    async with mounted_app(mcp, on_request=record) as (http, _):
        async with client_via_http(http) as first:
            first_result = await first.list_tools()
        async with client_via_http(http) as second:
            second_result = await second.call_tool("echo", {"text": "again"})

    assert {tool.name for tool in first_result.tools} == {"echo"}
    assert second_result == snapshot(
        CallToolResult(content=[TextContent(text="again")], structured_content={"result": "again"})
    )
    distinct = set(session_ids)
    assert len(distinct) == 2, f"expected two distinct session ids across the two connections, saw {distinct}"


@requirement("flow:compat:dual-transport-server")
async def test_one_server_serves_streamable_http_and_sse_clients_concurrently() -> None:
    """Both transports dispatch into the same server's handlers despite independent connection management.

    Uses MCPServer because the low-level Server has no SSE convenience; the entry is about hosting
    composition, not the low-level API.
    """
    mcp = MCPServer("dual")

    @mcp.tool()
    def echo(text: str) -> str:
        """Return the input unchanged."""
        return text

    async with (
        mounted_app(mcp) as (http, _),
        connect_over_sse(mcp) as sse_client,
        client_via_http(http) as shttp_client,
    ):
        with anyio.fail_after(5):
            shttp_result = await shttp_client.call_tool("echo", {"text": "via http"})
            sse_result = await sse_client.call_tool("echo", {"text": "via sse"})

    assert shttp_result == snapshot(
        CallToolResult(content=[TextContent(text="via http")], structured_content={"result": "via http"})
    )
    assert sse_result == snapshot(
        CallToolResult(content=[TextContent(text="via sse")], structured_content={"result": "via sse"})
    )
