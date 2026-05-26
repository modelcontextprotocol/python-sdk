"""Cancellation interactions against the low-level Server, driven through the public Client API.

There is no client-side cancellation API: cancelling means sending a CancelledNotification
carrying the request id, which only the server-side handler can observe (`ctx.request_id`), so
these tests capture the id from inside the blocked handler before cancelling. The handler blocks
on an Event rather than a sleep, and every wait is bounded by `anyio.fail_after`.
"""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolResult, ErrorData, TextContent
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("protocol:cancel:in-flight")
@requirement("protocol:cancel:handler-abort-propagates")
async def test_cancellation_stops_in_flight_handler() -> None:
    """Cancelling an in-flight request interrupts its handler and fails the pending call.

    The server answers the cancelled request with an error response (the spec says it should
    not respond at all; see the divergence note on the requirement), so the caller's pending
    request raises rather than hanging.
    """
    started = anyio.Event()
    handler_cancelled = anyio.Event()
    request_ids: list[types.RequestId] = []
    errors: list[ErrorData] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        assert ctx.request_id is not None
        request_ids.append(ctx.request_id)
        started.set()
        try:
            await anyio.Event().wait()  # blocks until cancelled; nothing ever sets this event
        except anyio.get_cancelled_exc_class():
            handler_cancelled.set()
            raise
        raise NotImplementedError  # unreachable: the wait above never completes normally

    server = Server("blocker", on_call_tool=call_tool)

    async with Client(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:

                async def call_and_capture_error() -> None:
                    with pytest.raises(MCPError) as exc_info:
                        await client.call_tool("block", {})
                    errors.append(exc_info.value.error)

                task_group.start_soon(call_and_capture_error)
                await started.wait()
                await client.session.send_notification(
                    types.CancelledNotification(
                        params=types.CancelledNotificationParams(request_id=request_ids[0], reason="user aborted")
                    )
                )

            await handler_cancelled.wait()

    assert errors == snapshot([ErrorData(code=0, message="Request cancelled")])


@requirement("protocol:cancel:server-survives")
async def test_session_serves_requests_after_cancellation() -> None:
    """A request cancelled mid-flight does not poison the session: the next request succeeds."""
    started = anyio.Event()
    request_ids: list[types.RequestId] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name="block", input_schema={"type": "object"}),
                types.Tool(name="echo", input_schema={"type": "object"}),
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        if params.name == "echo":
            return CallToolResult(content=[TextContent(text="still alive")])
        assert ctx.request_id is not None
        request_ids.append(ctx.request_id)
        started.set()
        await anyio.Event().wait()  # blocks until cancelled
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:

                async def call_and_swallow_cancellation_error() -> None:
                    with pytest.raises(MCPError):
                        await client.call_tool("block", {})

                task_group.start_soon(call_and_swallow_cancellation_error)
                await started.wait()
                await client.session.send_notification(
                    types.CancelledNotification(params=types.CancelledNotificationParams(request_id=request_ids[0]))
                )

            result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="still alive")]))


@requirement("protocol:cancel:unknown-id-ignored")
async def test_cancellation_for_unknown_request_is_ignored() -> None:
    """A cancellation referencing a request id that is not in flight is ignored without error."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="echo", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        return CallToolResult(content=[TextContent(text="unbothered")])

    server = Server("calm", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        await client.session.send_notification(
            types.CancelledNotification(params=types.CancelledNotificationParams(request_id=9999))
        )
        result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="unbothered")]))
