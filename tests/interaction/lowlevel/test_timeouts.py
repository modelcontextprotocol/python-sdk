"""Request timeouts against the low-level Server, driven through the public Client API.

The handler blocks on an event that is never set, so the awaited response can never arrive and
any positive timeout fires deterministically on the next event-loop pass. The timeout is therefore
set to an effectively-zero duration: the tests add no wall-clock time to the suite. (Zero itself
cannot be used: a falsy read_timeout_seconds is silently treated as "no timeout".)
"""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import REQUEST_TIMEOUT, CallToolResult, ErrorData, TextContent
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("timeouts:per-request")
async def test_request_timeout_fails_the_pending_call() -> None:
    """A request whose response does not arrive within its read timeout fails with a timeout error.

    No cancellation is sent to the server (see the divergence note on the requirement): the handler
    starts and is still running after the caller has already given up. The test waits for the
    handler to have started only after the timeout has fired, so the timeout itself races nothing.
    """
    handler_started = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        handler_started.set()
        await anyio.Event().wait()  # blocks until the session is torn down
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_call_tool=call_tool)

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("block", {}, read_timeout_seconds=0.000001)

        # The request was already on the wire: the handler still runs even though the caller gave up.
        with anyio.fail_after(5):
            await handler_started.wait()

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=REQUEST_TIMEOUT,
            message="Timed out while waiting for response to CallToolRequest. Waited 1e-06 seconds.",
        )
    )


@requirement("timeouts:session-survives")
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
        await anyio.Event().wait()  # blocks until the session is torn down
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        with pytest.raises(MCPError):
            await client.call_tool("block", {}, read_timeout_seconds=0.000001)

        result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="still alive")]))


@requirement("timeouts:session-default")
async def test_session_level_timeout_applies_to_every_request() -> None:
    """A read timeout configured on the client applies to requests that do not set their own.

    The session default also governs the initialize handshake, so this is the one test in the
    suite that needs a real (50ms) timeout: it must be long enough for the in-process handshake
    to complete and is then waited out in full by the blocked tool call.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        await anyio.Event().wait()  # blocks until the session is torn down
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_call_tool=call_tool)

    async with Client(server, read_timeout_seconds=0.05) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("block", {})

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=REQUEST_TIMEOUT,
            message="Timed out while waiting for response to CallToolRequest. Waited 0.05 seconds.",
        )
    )
