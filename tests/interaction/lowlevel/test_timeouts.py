"""Request timeouts against the low-level Server, driven through the public Client API.

The handler blocks on an event that is never set, so the awaited response can never arrive and
any positive timeout fires deterministically on the next event-loop pass. Per-request timeouts are
set to an effectively-zero duration; the session-level test runs on trio's virtual clock instead
(see the comment there). Either way the tests add no wall-clock time to the suite. (Zero would
also time out immediately, but a tiny positive value keeps the duration visible in the
cancellation reason these tests snapshot.)
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


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


@requirement("protocol:timeout:basic")
@requirement("protocol:timeout:sends-cancellation")
async def test_request_timeout_fails_the_pending_call() -> None:
    """A request whose response does not arrive within its read timeout fails with a timeout error.

    The timeout is followed by notifications/cancelled, which interrupts the server's handler.
    """
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
    """A server-initiated request that times out fails server-side and cancels the client's work.

    The sampling callback answers only after the server gave up; the late response is discarded.
    """
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
    """A timed-out request does not poison the session: the next request succeeds."""

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


# A session-level timeout cannot use the effectively-zero pattern above: it also governs the
# initialize handshake, which must complete before the blocked tool call can wait the timeout
# out in full. Any real-clock margin is a bet against CI scheduler stalls (a 50ms value lost
# that bet in CI; the in-process handshake tail reaches ~190ms on a loaded windows runner), so
# this test runs on trio's virtual clock instead. With autojump, time advances only when every
# task is blocked: the handshake always has a runnable task and therefore cannot time out no
# matter how slow the runner, and once the tool call blocks on the never-answered request the
# run goes idle and the clock jumps straight to the deadline — deterministic, with no real wait.
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
