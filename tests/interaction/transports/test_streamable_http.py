"""Tests for the interaction model over the streamable HTTP transport, entirely in process.

The Starlette app a real deployment would hand to uvicorn is driven through the suite's
streaming ASGI bridge instead: the full HTTP framing layer runs (session ids, SSE and JSON
response encoding, stateful and stateless session management) with no sockets, threads, or
subprocesses, so these tests are as deterministic as the in-memory ones. Because the bridge
streams each response as the server produces it, full-duplex behaviour works too: a
server-initiated request nested inside a still-open call round-trips while that call's SSE
response remains open.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest
from inline_snapshot import snapshot
from pydantic import BaseModel

from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolResult,
    ElicitRequestParams,
    ElicitResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    TextContent,
)
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement
from tests.interaction.transports._bridge import StreamingASGITransport

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
        """Elicit a confirmation from the client and report the outcome."""
        answer = await ctx.elicit("Proceed?", Confirmation)
        # In stateless mode the elicit raises before this point: there is no session to call back through.
        assert isinstance(answer, AcceptedElicitation)
        return f"confirmed={answer.data.confirmed}"

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
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url="http://127.0.0.1:8000") as http:
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
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url="http://127.0.0.1:8000") as http:
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
async def test_unrelated_server_messages_arrive_on_the_standalone_stream() -> None:
    """A server message with no related request reaches the client through the standalone GET stream.

    The log notification is related to the tool call and travels on that call's own SSE stream;
    the resource-updated notification is not related to any request, so the only way it can reach
    the client is the standalone stream the client opens after initialization. Delivery order
    across the two streams is not guaranteed, so the unrelated message is awaited rather than
    assumed to beat the tool result.
    """
    received: list[IncomingMessage] = []
    resource_update_seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        if isinstance(message, ResourceUpdatedNotification):
            resource_update_seen.set()

    server = _smoke_server()
    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url="http://127.0.0.1:8000") as http:
            transport = streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)
            async with Client(transport, message_handler=collect) as client:
                result = await client.call_tool("announce", {})
                with anyio.fail_after(5):
                    await resource_update_seen.wait()

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="announced")], structured_content={"result": "announced"})
    )
    # The related log notification rides the call's stream; the unrelated resource-updated
    # notification rides the standalone stream. Both arrive, nothing else does.
    assert [message for message in received if isinstance(message, LoggingMessageNotification)] == snapshot(
        [LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="about to announce"))]
    )
    assert [message for message in received if isinstance(message, ResourceUpdatedNotification)] == snapshot(
        [ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri="file:///watched.txt"))]
    )
    assert len(received) == 2


@requirement("transport:streamable-http:server-to-client")
async def test_server_initiated_elicitation_round_trips_during_a_tool_call() -> None:
    """An elicitation issued mid-call reaches the client and its answer reaches the handler over stateful HTTP.

    The elicitation request travels on the still-open SSE response of the tool call that triggered
    it, and the client's answer arrives as a separate POST -- the full-duplex exchange the
    streamable HTTP transport exists to provide.
    """
    asked: list[ElicitRequestParams] = []

    async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params)
        return ElicitResult(action="accept", content={"confirmed": True})

    server = _smoke_server()
    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url="http://127.0.0.1:8000") as http:
            transport = streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)
            async with Client(transport, elicitation_callback=answer) as client:
                # Bounded because a harness regression here historically meant deadlock, not failure.
                with anyio.fail_after(5):
                    result = await client.call_tool("ask", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="confirmed=True")], structured_content={"result": "confirmed=True"})
    )
    assert [params.message for params in asked] == snapshot(["Proceed?"])
