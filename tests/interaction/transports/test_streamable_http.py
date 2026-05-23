"""Smoke tests for the interaction model over the streamable HTTP transport, entirely in process.

The Starlette app a real deployment would hand to uvicorn is driven through httpx's ASGI
transport instead: the full HTTP framing layer runs (session ids, SSE and JSON response
encoding, stateful and stateless session management) with no sockets, threads, or subprocesses,
so these tests are as deterministic as the in-memory ones.

The ASGI client buffers each response in full before the client sees any of it. Request,
response, and notification flows are unaffected -- notifications are written to the request's
SSE stream before the response and arrive in order -- but a server-initiated request nested
inside a still-open call would deadlock, so that scenario is deferred to the real-socket
transport tests (see the `transport:streamable-http:server-to-client` requirement).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from inline_snapshot import snapshot
from pydantic import BaseModel

from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    TextContent,
)
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _smoke_server() -> MCPServer:
    """A server exercising one example of each message shape the smoke tests need."""
    mcp = MCPServer("smoke", instructions="Talk to the smoke server.")

    @mcp.tool()
    def echo(text: str) -> str:
        """Echo the text back."""
        return text

    @mcp.tool()
    def fail() -> str:
        """Always fails."""
        raise ValueError("deliberately broken")

    @mcp.tool()
    async def narrate(ctx: Context) -> str:
        """Send a log message and a progress update, then return."""
        await ctx.info("starting")
        await ctx.report_progress(1, 2)
        await ctx.info("finishing")
        return "narrated"

    class Confirmation(BaseModel):
        confirmed: bool

    @mcp.tool()
    async def ask(ctx: Context) -> str:
        """Attempt a server-initiated elicitation."""
        await ctx.elicit("Proceed?", Confirmation)
        raise NotImplementedError  # only called in stateless mode, where the elicit cannot succeed

    @mcp.tool()
    async def announce(ctx: Context) -> str:
        """Send one notification related to this request and one that is not."""
        await ctx.info("about to announce")
        await ctx.session.send_resource_updated("file:///watched.txt")
        return "announced"

    return mcp


@asynccontextmanager
async def _connected(
    mcp: MCPServer, *, stateless_http: bool = False, json_response: bool = False
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server through the in-process streamable HTTP stack."""
    # DNS-rebinding protection validates Host/Origin headers against a real network attack that
    # cannot exist for an in-process ASGI app; leaving it on would also pull the origin-validation
    # branch (deliberately uncovered in src) into coverage.
    app = mcp.streamable_http_app(
        stateless_http=stateless_http,
        json_response=json_response,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            transport = streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)
            async with Client(transport) as client:
                yield client


@requirement("transport:streamable-http:stateful")
async def test_initialize_and_call_a_tool_over_streamable_http() -> None:
    """The handshake and a tool round trip work through the stateful SSE framing."""
    async with _connected(_smoke_server()) as client:
        assert client.initialize_result.server_info.name == "smoke"
        assert client.initialize_result.instructions == "Talk to the smoke server."
        result = await client.call_tool("echo", {"text": "over http"})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="over http")], structured_content={"result": "over http"})
    )


@requirement("transport:streamable-http:stateful")
async def test_tool_errors_round_trip_over_streamable_http() -> None:
    """A tool execution error crosses the HTTP framing as an is_error result, not a transport failure."""
    async with _connected(_smoke_server()) as client:
        result = await client.call_tool("fail", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="Error executing tool fail: deliberately broken")], is_error=True)
    )


@requirement("transport:streamable-http:json-response")
async def test_tool_call_over_streamable_http_with_json_responses() -> None:
    """The round trip works when the server answers with a single JSON body instead of an SSE stream."""
    async with _connected(_smoke_server(), json_response=True) as client:
        assert client.initialize_result.server_info.name == "smoke"
        result = await client.call_tool("echo", {"text": "as json"})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="as json")], structured_content={"result": "as json"})
    )


@requirement("transport:streamable-http:stateless")
async def test_tool_calls_over_stateless_streamable_http() -> None:
    """Consecutive requests each succeed against a stateless server with no session to share."""
    async with _connected(_smoke_server(), stateless_http=True) as client:
        first = await client.call_tool("echo", {"text": "first"})
        second = await client.call_tool("echo", {"text": "second"})

    assert first == snapshot(
        CallToolResult(content=[TextContent(text="first")], structured_content={"result": "first"})
    )
    assert second == snapshot(
        CallToolResult(content=[TextContent(text="second")], structured_content={"result": "second"})
    )


@requirement("transport:streamable-http:notifications")
async def test_notifications_during_a_tool_call_arrive_before_the_response() -> None:
    """Log and progress notifications emitted mid-call are delivered on the call's SSE stream in order."""
    logs: list[LoggingMessageNotificationParams] = []
    progress_updates: list[tuple[float, float | None, str | None]] = []

    async def collect_log(params: LoggingMessageNotificationParams) -> None:
        logs.append(params)

    async def collect_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_updates.append((progress, total, message))

    server = _smoke_server()
    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            transport = streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)
            async with Client(transport, logging_callback=collect_log) as client:
                result = await client.call_tool("narrate", {}, progress_callback=collect_progress)

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="narrated")], structured_content={"result": "narrated"})
    )
    assert [params.data for params in logs] == snapshot(["starting", "finishing"])
    assert progress_updates == snapshot([(1.0, 2.0, None)])


@requirement("transport:streamable-http:stateless-restrictions")
async def test_stateless_streamable_http_rejects_server_initiated_requests() -> None:
    """A handler that tries to call back to the client in stateless mode fails: there is no session."""
    async with _connected(_smoke_server(), stateless_http=True) as client:
        result = await client.call_tool("ask", {})

    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    # The exact message is the StatelessModeNotSupported exception text wrapped by the tool-error
    # path; pin the stable prefix rather than the full exception prose.
    assert result.content[0].text.startswith("Error executing tool ask:")


@requirement("transport:streamable-http:unrelated-messages")
async def test_unrelated_server_messages_are_not_delivered_without_a_listening_stream() -> None:
    """A server message with no related request goes to the standalone GET stream, not the call's stream.

    The client never opens the standalone stream, so the resource-updated notification is silently
    dropped. The log notification sent by the same tool IS related to the call and does arrive,
    proving the collector works and making the absence of the unrelated one meaningful. This is
    the transport behaviour that makes `related_request_id` matter.
    """
    received: list[IncomingMessage] = []

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    server = _smoke_server()
    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            transport = streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)
            async with Client(transport, message_handler=collect) as client:
                result = await client.call_tool("announce", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="announced")], structured_content={"result": "announced"})
    )
    # Only the related log notification arrives; the resource-updated notification went to the
    # standalone stream nobody is reading.
    assert received == snapshot(
        [LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="about to announce"))]
    )
