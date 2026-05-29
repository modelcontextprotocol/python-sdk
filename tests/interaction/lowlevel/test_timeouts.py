"""Request timeouts against the low-level Server, driven through the public client API.

The handler blocks on an event that is never set, so the awaited response can never arrive and
any positive timeout fires deterministically on the next event-loop pass. The timeout is therefore
set to an effectively-zero duration: the tests add no wall-clock time to the suite. (Zero itself
cannot be used: a falsy read_timeout_seconds is silently treated as "no timeout".)
"""

from datetime import timedelta
from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import McpError, types
from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, ErrorData, TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("protocol:timeout:basic")
@requirement("protocol:timeout:sends-cancellation")
async def test_request_timeout_fails_the_pending_call(connect: Connect) -> None:
    """A request whose response does not arrive within its read timeout fails with a timeout error.

    No cancellation is sent to the server (see the divergence note on the requirement): the handler
    starts and is still running after the caller has already given up. The test waits for the
    handler to have started only after the timeout has fired, so the timeout itself races nothing.
    """
    handler_started = anyio.Event()
    server: Server[Any] = Server("blocker")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "block"
        handler_started.set()
        await anyio.Event().wait()  # blocks until the session is torn down
        raise NotImplementedError  # unreachable

    async with connect(server) as client:
        with pytest.raises(McpError) as exc_info:
            await client.call_tool("block", {}, read_timeout_seconds=timedelta(seconds=0.000001))

        # The request was already on the wire: the handler still runs even though the caller gave up.
        with anyio.fail_after(5):
            await handler_started.wait()

    assert exc_info.value.error == snapshot(
        ErrorData(code=408, message="Timed out while waiting for response to ClientRequest. Waited 1e-06 seconds.")
    )


@requirement("protocol:timeout:session-survives")
async def test_session_serves_requests_after_timeout(connect: Connect) -> None:
    """A timed-out request does not poison the session: the next request succeeds."""
    server: Server[Any] = Server("blocker")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name="block", inputSchema={"type": "object"}),
            types.Tool(name="echo", inputSchema={"type": "object"}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name == "echo":
            return [TextContent(type="text", text="still alive")]
        await anyio.Event().wait()  # blocks until the session is torn down
        raise NotImplementedError  # unreachable

    async with connect(server) as client:
        with pytest.raises(McpError):
            await client.call_tool("block", {}, read_timeout_seconds=timedelta(seconds=0.000001))

        result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="still alive")]))


@requirement("protocol:timeout:session-default")
async def test_session_level_timeout_applies_to_every_request(connect: Connect) -> None:
    """A read timeout configured on the client applies to requests that do not set their own."""
    server: Server[Any] = Server("blocker")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "block"
        await anyio.Event().wait()  # blocks until the session is torn down
        raise NotImplementedError  # unreachable

    # The one real wall-clock wait in the suite, and it cannot be made effectively zero like the
    # per-request timeouts: a session-level timeout also governs the initialize handshake, so the
    # value must be long enough for the in-process handshake to complete before the blocked tool
    # call waits it out in full. 50ms buys a ~50x safety margin over the handshake's actual
    # latency; lowering it only erodes the margin against CI scheduler jitter without saving
    # anything perceptible.
    async with connect(server, read_timeout_seconds=timedelta(seconds=0.05)) as client:
        with pytest.raises(McpError) as exc_info:
            await client.call_tool("block", {})

    assert exc_info.value.error == snapshot(
        ErrorData(code=408, message="Timed out while waiting for response to ClientRequest. Waited 0.05 seconds.")
    )
