"""Request timeouts against the low-level Server, driven through the public Client API.

Handlers block on a never-set event, so any positive timeout fires deterministically at no
wall-clock cost. Per-request timeouts are tiny but nonzero so the duration stays visible in the
snapshotted cancellation reason; the session-level test runs on trio's virtual clock instead.
"""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import REQUEST_TIMEOUT, CallToolResult, ErrorData, JSONRPCNotification, TextContent
from trio.testing import MockClock

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared.message import SessionMessage
from tests.interaction._helpers import RecordingTransport
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("protocol:timeout:basic")
@requirement("protocol:timeout:sends-cancellation")
async def test_request_timeout_fails_the_pending_call() -> None:
    """The timeout error is followed by notifications/cancelled, which interrupts the server's handler."""
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        handler_started.set()
        try:
            await anyio.Event().wait()  # blocks until the courtesy cancellation interrupts it
        except anyio.get_cancelled_exc_class():
            handler_cancelled.set()
            raise
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_call_tool=call_tool)

    async with Client(server, mode="legacy") as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("block", {}, read_timeout_seconds=0.000001)

        # The request was already on the wire: the handler started and was then cancelled.
        with anyio.fail_after(5):
            await handler_started.wait()
            await handler_cancelled.wait()

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=REQUEST_TIMEOUT,
            message="Request 'tools/call' timed out",
        )
    )


@requirement("protocol:timeout:basic")
@requirement("protocol:timeout:sends-cancellation")
async def test_server_request_timeout_sends_cancellation_to_the_client() -> None:
    """The sampling callback answers only after the server gave up; the late response is discarded."""
    release = anyio.Event()
    callback_started = anyio.Event()
    errors: list[ErrorData] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="impatient", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "impatient"
        request = types.CreateMessageRequest(
            params=types.CreateMessageRequestParams(
                messages=[types.SamplingMessage(role="user", content=TextContent(text="Say hello."))],
                max_tokens=8,
            )
        )
        with pytest.raises(MCPError) as exc_info:
            await ctx.session.send_request(request, types.CreateMessageResult, request_read_timeout_seconds=0.000001)
        errors.append(exc_info.value.error)
        release.set()
        return CallToolResult(content=[TextContent(text="gave up")])

    server = Server("impatient", on_list_tools=list_tools, on_call_tool=call_tool)
    recording = RecordingTransport(InMemoryTransport(server))

    async def sampling_callback(
        context: ClientRequestContext, params: types.CreateMessageRequestParams
    ) -> types.CreateMessageResult:
        callback_started.set()
        with anyio.fail_after(5):
            await release.wait()
        return types.CreateMessageResult(role="assistant", content=TextContent(text="too late"), model="test-model")

    async with Client(recording, mode="legacy", sampling_callback=sampling_callback) as client:
        result = await client.call_tool("impatient", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="gave up")]))
    assert callback_started.is_set()
    assert errors == snapshot([ErrorData(code=REQUEST_TIMEOUT, message="Request 'sampling/createMessage' timed out")])
    cancellations = [
        item.message
        for item in recording.received
        if isinstance(item, SessionMessage)
        and isinstance(item.message, JSONRPCNotification)
        and item.message.method == "notifications/cancelled"
    ]
    # requestId 1 is the sampling request, the server's first outbound request.
    assert [notification.params for notification in cancellations] == snapshot(
        [{"requestId": 1, "reason": "timed out after 1e-06s"}]
    )


@requirement("protocol:timeout:session-survives")
async def test_session_serves_requests_after_timeout() -> None:
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
        await anyio.Event().wait()  # blocks until the courtesy cancellation interrupts it
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server, mode="legacy") as client:
        with pytest.raises(MCPError):
            await client.call_tool("block", {}, read_timeout_seconds=0.000001)

        result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="still alive")]))


# The session-level timeout also governs the initialize handshake, so the effectively-zero pattern can't work here,
# and real-clock margins lose to CI scheduler stalls (50ms did; windows handshake tails hit ~190ms). Trio's autojump
# clock advances only when all tasks block: the handshake can't time out, and the blocked call jumps to its deadline.
@requirement("protocol:timeout:session-default")
@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_session_level_timeout_applies_to_every_request() -> None:
    """A read timeout configured on the client applies to requests that do not set their own."""

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        await anyio.Event().wait()  # blocks until the courtesy cancellation interrupts it
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_call_tool=call_tool)

    async with Client(server, mode="legacy", read_timeout_seconds=0.05) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("block", {})

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=REQUEST_TIMEOUT,
            message="Request 'tools/call' timed out",
        )
    )
