"""Behaviour specific to the streamable HTTP transport, exercised entirely in process.

Transport-agnostic behaviour is covered by the `connect`-fixture matrix, which runs the rest of
the suite over this transport as well; this file only pins what cannot be observed in memory: the
server's stateless and JSON-response modes, the standalone GET stream, and the full-duplex
server-initiated exchange on a still-open call. Every test drives the server's real Starlette app
through the suite's streaming ASGI bridge — no sockets, threads, or subprocesses.
"""

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_REQUEST,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    TextContent,
    jsonrpc_message_adapter,
)
from pydantic import BaseModel

from mcp.client import ClientRequestContext, IncomingMessage
from mcp.server import Server, ServerRequestContext
from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.streamable_http import REQUEST_CANCELLED
from mcp.shared.exceptions import MCPError
from tests.interaction._connect import (
    base_headers,
    connect_over_streamable_http,
    initialize_body,
    initialize_via_http,
    mounted_app,
    post_jsonrpc,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _smoke_server() -> MCPServer:
    """A server exercising each message shape the transport-specific tests need."""
    mcp = MCPServer("smoke", instructions="Talk to the smoke server.")

    @mcp.tool()
    def echo(text: str) -> str:
        """Echo the text back."""
        return text

    class Confirmation(BaseModel):
        confirmed: bool

    @mcp.tool()
    async def ask(ctx: Context) -> str:
        """Elicit a confirmation from the client and report the outcome."""
        answer = await ctx.elicit("Proceed?", Confirmation)
        # In stateless and JSON-response modes the elicit raises before this point: there is no
        # request-scoped channel to call back through.
        assert isinstance(answer, AcceptedElicitation)
        return f"confirmed={answer.data.confirmed}"

    @mcp.tool()
    async def announce(ctx: Context) -> str:
        """Send one notification related to this request and one that is not."""
        await ctx.info("about to announce")  # pyright: ignore[reportDeprecated]
        await ctx.session.send_resource_updated("file:///watched.txt")
        return "announced"

    return mcp


@requirement("transport:streamable-http:json-response")
@requirement("client-transport:http:json-response-parsed")
async def test_tool_call_over_streamable_http_with_json_responses() -> None:
    """The round trip works when the server answers with a single JSON body instead of an SSE stream."""
    async with connect_over_streamable_http(_smoke_server(), json_response=True) as client:
        assert client.server_info is not None
        assert client.server_info.name == "smoke"
        result = await client.call_tool("echo", {"text": "as json"})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="as json")], structured_content={"result": "as json"})
    )


@requirement("transport:streamable-http:stateless")
async def test_tool_calls_over_stateless_streamable_http() -> None:
    """Consecutive requests each succeed against a stateless server with no session to share."""
    async with connect_over_streamable_http(_smoke_server(), stateless_http=True) as client:
        first = await client.call_tool("echo", {"text": "first"})
        second = await client.call_tool("echo", {"text": "second"})

    assert first == snapshot(
        CallToolResult(content=[TextContent(text="first")], structured_content={"result": "first"})
    )
    assert second == snapshot(
        CallToolResult(content=[TextContent(text="second")], structured_content={"result": "second"})
    )


@requirement("transport:streamable-http:stateless-restrictions")
async def test_stateless_streamable_http_rejects_server_initiated_requests() -> None:
    """A handler that tries to call back to the client in stateless mode fails: there is no
    back-channel for server-initiated requests. The resulting ``NoBackChannelError`` is an
    ``MCPError``, so it surfaces as a top-level JSON-RPC error rather than an
    ``isError`` result."""
    async with connect_over_streamable_http(_smoke_server(), stateless_http=True) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("ask", {})

    assert exc_info.value.error.code == INVALID_REQUEST


@requirement("transport:streamable-http:json-response-restrictions")
async def test_json_response_streamable_http_rejects_request_scoped_server_requests() -> None:
    """A handler that calls back to the client mid-request fails fast when the server answers with
    JSON: the one response body cannot carry the nested `elicitation/create`, so the request-scoped
    channel raises `NoBackChannelError` (a top-level `MCPError`) instead of parking a waiter no reply
    could ever reach. Bounded, because before the fix this call hung until it timed out."""
    async with connect_over_streamable_http(_smoke_server(), json_response=True) as client:
        with anyio.fail_after(5), pytest.raises(MCPError) as exc_info:
            await client.call_tool("ask", {})

    assert exc_info.value.error.code == INVALID_REQUEST


@requirement("transport:streamable-http:json-response-restrictions")
@requirement("transport:streamable-http:unrelated-messages")
@requirement("hosting:http:standalone-sse")
async def test_json_response_streamable_http_delivers_only_unrelated_notifications() -> None:
    """In JSON-response mode the call's own log notification has no stream to ride and never
    reaches the client, while the tool result comes back as the JSON body and the unrelated
    resource-updated notification arrives on the standalone stream. The handler writes both
    notifications before returning, so once the result and the unrelated message are in, no
    request-scoped message can still be in flight."""
    received: list[IncomingMessage] = []
    server_message_seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        server_message_seen.set()

    async with connect_over_streamable_http(_smoke_server(), json_response=True, message_handler=collect) as client:
        with anyio.fail_after(5):
            result = await client.call_tool("announce", {})
            await server_message_seen.wait()

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="announced")], structured_content={"result": "announced"})
    )
    assert received == snapshot(
        [ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri="file:///watched.txt"))]
    )


@requirement("transport:streamable-http:notifications")
@requirement("transport:streamable-http:unrelated-messages")
@requirement("hosting:http:standalone-sse")
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

    async with connect_over_streamable_http(_smoke_server(), message_handler=collect) as client:
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


@requirement("transport:streamable-http:stateful")
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

    async with connect_over_streamable_http(_smoke_server(), elicitation_callback=answer) as client:
        # Bounded because a harness regression here historically meant deadlock, not failure.
        with anyio.fail_after(5):
            result = await client.call_tool("ask", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="confirmed=True")], structured_content={"result": "confirmed=True"})
    )
    assert [params.message for params in asked] == snapshot(["Proceed?"])


@requirement("transport:streamable-http:cancelled-request-terminated")
@pytest.mark.parametrize("json_response", [True, False], ids=["json-response", "sse-response"])
async def test_cancelled_request_is_terminated_with_request_cancelled(json_response: bool) -> None:
    """A cancelled request's POST completes carrying the `REQUEST_CANCELLED` terminal error.

    The 2025-era wire ends a request only with a response, so this transport answers the
    settled-unanswered request with `REQUEST_CANCELLED` (the dispatcher writes nothing on the
    other transports). Driven with raw httpx2 because the observable is the HTTP exchange
    itself, which a Client abandoning its own call would tear down first.
    """
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()
    call_request_id = 2

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            handler_cancelled.set()
            raise
        raise NotImplementedError  # unreachable: only cancellation ends the sleep

    server = Server("blocker", on_call_tool=call_tool)
    call_body = JSONRPCRequest(
        jsonrpc="2.0",
        id=call_request_id,
        method="tools/call",
        params=CallToolRequestParams(name="block", arguments={}).model_dump(by_alias=True, mode="json"),
    ).model_dump(by_alias=True, exclude_none=True)
    cancel_body = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": call_request_id},
    }
    call_answers: list[JSONRPCMessage] = []

    async with mounted_app(server, json_response=json_response) as (http, _manager):
        if json_response:
            # The SSE-reading handshake helper does not apply: JSON mode answers initialize with JSON.
            initialized = await http.post("/mcp", json=initialize_body(), headers=base_headers())
            session_id = initialized.headers["mcp-session-id"]
            ready = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=base_headers(session_id=session_id),
            )
            assert ready.status_code == 202
        else:
            session_id = await initialize_via_http(http)

        async def post_call() -> None:
            if json_response:
                response = await http.post("/mcp", json=call_body, headers=base_headers(session_id=session_id))
                call_answers.append(jsonrpc_message_adapter.validate_json(response.content))
            else:
                _, messages = await post_jsonrpc(http, call_body, session_id=session_id)
                call_answers.extend(messages)

        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:  # pragma: no branch
                task_group.start_soon(post_call)
                await handler_started.wait()
                cancelled = await http.post("/mcp", json=cancel_body, headers=base_headers(session_id=session_id))
                assert cancelled.status_code == 202
                await handler_cancelled.wait()
                # The call's POST must now complete on its own; the task group waits for it.

    assert call_answers == [
        JSONRPCError(
            jsonrpc="2.0",
            id=call_request_id,
            error=ErrorData(code=REQUEST_CANCELLED, message="Request cancelled"),
        )
    ]
