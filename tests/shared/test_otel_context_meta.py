"""Test that OpenTelemetry context is properly injected into _meta."""

# ruff: noqa: E501

from dataclasses import dataclass

import anyio
import pytest
from anyio.streams.memory import MemoryObjectSendStream
from inline_snapshot import snapshot
from opentelemetry import propagate, trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from mcp import ClientSession, types
from mcp.server import MCPServer
from mcp.server.mcpserver.server import Context
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    SamplingMessage,
    TextContent,
)
from mcp.types._types import RequestParamsMeta
from mcp.types.jsonrpc import JSONRPCMessage

# Test span to set as active in client
SPAN_IN_CLIENT = NonRecordingSpan(
    SpanContext(
        trace_id=0x123,
        span_id=0xABC,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
)
# Test span to set as active in server for backwards calls like sampling
SPAN_IN_SERVER = NonRecordingSpan(
    SpanContext(
        trace_id=0x456,
        span_id=0xDEF,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
)


@pytest.fixture
def server() -> MCPServer:
    mcp = MCPServer("test_server")

    @mcp.tool()
    async def my_tool() -> str:
        return "hello"

    @mcp.tool()
    async def tool_with_progress(ctx: Context[ServerSession, None]) -> str:
        """Send progress to the client, which should propagate _meta."""
        with trace.use_span(SPAN_IN_SERVER):
            await ctx.report_progress(progress=0.5, total=1.0)
            return "tool result"

    @mcp.tool()
    async def tool_with_sampling(topic: str, ctx: Context[ServerSession, None]) -> str:
        """Uses LLM sampling to call back to the client, which should propagate _meta."""
        with trace.use_span(SPAN_IN_SERVER):
            await ctx.session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text=f"Tell me about {topic}"),
                    )
                ],
                max_tokens=50,
            )
        return "ran sampling"

    @mcp.tool()
    async def tool_that_checks_trace_context() -> str:
        """Returns current span details to verify parent propagation."""
        return trace.format_trace_id(trace.get_current_span().get_span_context().trace_id)

    return mcp


@pytest.fixture(autouse=True)
def global_propagator():
    original_propagator = propagate.get_global_textmap()
    propagate.set_global_textmap(TraceContextTextMapPropagator())
    yield
    propagate.set_global_textmap(original_propagator)


@dataclass
class PatchedClient:
    session: ClientSession
    client_to_server_messages: list[JSONRPCMessage]
    server_to_client_messages: list[JSONRPCMessage]


@pytest.fixture
async def patched_client(server: MCPServer, monkeypatch: pytest.MonkeyPatch):
    client_to_server_messages: list[JSONRPCMessage] = []
    server_to_client_messages: list[JSONRPCMessage] = []
    low_server = server._lowlevel_server

    async def sampling_callback(
        context: RequestContext[ClientSession], params: types.CreateMessageRequestParams
    ) -> types.CreateMessageResult:
        current_trace_id = trace.format_trace_id(trace.get_current_span().get_span_context().trace_id)
        return types.CreateMessageResult(
            role="assistant", content=TextContent(type="text", text=current_trace_id), model="foomodel"
        )

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        def patch_stream_send(capture_to: list[JSONRPCMessage], stream: MemoryObjectSendStream[SessionMessage]):
            original_send = stream.send

            async def send_capture(item: SessionMessage) -> None:
                capture_to.append(item.message)
                await original_send(item)

            monkeypatch.setattr(stream, "send", send_capture)

        async with (
            anyio.create_task_group() as tg,
            ClientSession(
                read_stream=client_read, write_stream=client_write, sampling_callback=sampling_callback
            ) as client_session,
        ):
            # Start server in background
            tg.start_soon(
                lambda: low_server.run(
                    server_read,
                    server_write,
                    low_server.create_initialization_options(),
                )
            )

            try:
                await client_session.initialize()
                # Call list_tools once before patching to warm up the client's tool schema cache
                # so that subsequent call_tool calls don't automatically trigger tools/list.
                await client_session.list_tools()

                patch_stream_send(client_to_server_messages, client_write)
                patch_stream_send(server_to_client_messages, server_write)
                yield PatchedClient(client_session, client_to_server_messages, server_to_client_messages)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_no_span_in_context(patched_client: PatchedClient):
    """Test that OTEL context is not injected when no span is active."""
    await patched_client.session.call_tool("my_tool")
    assert patched_client.client_to_server_messages == snapshot(
        [JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/call", params={"name": "my_tool"})]
    )


@pytest.mark.anyio
async def test_with_span_in_context(patched_client: PatchedClient):
    """Test that OTEL context is injected into the _meta field of a request."""
    with trace.use_span(SPAN_IN_CLIENT):
        await patched_client.session.call_tool("my_tool")

    assert patched_client.client_to_server_messages == snapshot(
        [
            JSONRPCRequest(
                jsonrpc="2.0",
                id=2,
                method="tools/call",
                params={
                    "_meta": {"traceparent": "00-00000000000000000000000000000123-0000000000000abc-01"},
                    "name": "my_tool",
                },
            )
        ]
    )


@pytest.mark.parametrize(
    "meta,expect_client_to_server",
    [
        (
            {"foo": "bar"},
            snapshot(
                [
                    JSONRPCRequest(
                        jsonrpc="2.0",
                        id=2,
                        method="tools/call",
                        params={
                            "_meta": {
                                "foo": "bar",
                                "traceparent": "00-00000000000000000000000000000123-0000000000000abc-01",
                            },
                            "name": "my_tool",
                        },
                    )
                ]
            ),
        ),
        (
            {"traceparent": "existing"},
            snapshot(
                [
                    JSONRPCRequest(
                        jsonrpc="2.0",
                        id=2,
                        method="tools/call",
                        params={
                            "_meta": {"traceparent": "00-00000000000000000000000000000123-0000000000000abc-01"},
                            "name": "my_tool",
                        },
                    )
                ]
            ),
        ),
    ],
)
@pytest.mark.anyio
async def test_with_existing_meta(
    patched_client: PatchedClient, meta: RequestParamsMeta | None, expect_client_to_server: list[JSONRPCMessage]
):
    with trace.use_span(SPAN_IN_CLIENT):
        await patched_client.session.call_tool("my_tool", meta=meta)

    assert patched_client.client_to_server_messages == expect_client_to_server


@pytest.mark.anyio
async def test_trace_context_extraction(patched_client: PatchedClient):
    """Test that OTEL context is successfully extracted on the receiving end."""

    with trace.use_span(SPAN_IN_CLIENT):
        result = await patched_client.session.call_tool("tool_that_checks_trace_context")

    # Verify that SPAN_IN_CLIENT was extracted and made it through to the handler
    assert result.content[0] == snapshot(TextContent(text="00000000000000000000000000000123"))


@pytest.mark.anyio
async def test_list_tools_with_span(patched_client: PatchedClient):
    """Test that OTEL context is injected into the _meta field of a tools/list request."""
    with trace.use_span(SPAN_IN_CLIENT):
        await patched_client.session.list_tools()

    assert patched_client.client_to_server_messages == snapshot(
        [JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/list")]
    )


@pytest.mark.anyio
async def test_tool_with_progress_propagates_to_client(patched_client: PatchedClient):
    """Test that trace context is propagated back to the client when server sends progress updates."""

    async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
        pass

    with trace.use_span(SPAN_IN_CLIENT):
        await patched_client.session.call_tool("tool_with_progress", progress_callback=progress_callback)

    assert patched_client.client_to_server_messages == snapshot(
        [
            JSONRPCRequest(
                jsonrpc="2.0",
                id=2,
                method="tools/call",
                params={
                    "_meta": {
                        "traceparent": "00-00000000000000000000000000000123-0000000000000abc-01",
                        "progressToken": 2,
                    },
                    "name": "tool_with_progress",
                },
            )
        ]
    )
    assert patched_client.server_to_client_messages == snapshot(
        [
            JSONRPCNotification(
                jsonrpc="2.0",
                method="notifications/progress",
                params={
                    "_meta": {"traceparent": "00-00000000000000000000000000000456-0000000000000def-01"},
                    "progressToken": 2,
                    "progress": 0.5,
                    "total": 1.0,
                },
            ),
            JSONRPCResponse(
                jsonrpc="2.0",
                id=2,
                result={
                    "content": [{"type": "text", "text": "tool result"}],
                    "structuredContent": {"result": "tool result"},
                    "isError": False,
                },
            ),
        ]
    )


@pytest.mark.anyio
async def test_server_side_sampling_propagates_to_client(patched_client: PatchedClient):
    """Test that trace context is propagated in the request from server to client during
    server-side sampling
    """
    with trace.use_span(SPAN_IN_CLIENT):
        await patched_client.session.call_tool("tool_with_sampling", arguments={"topic": "testing"})

    assert patched_client.client_to_server_messages == snapshot(
        [
            JSONRPCRequest(
                jsonrpc="2.0",
                id=2,
                method="tools/call",
                params={
                    "_meta": {"traceparent": "00-00000000000000000000000000000123-0000000000000abc-01"},
                    "name": "tool_with_sampling",
                    "arguments": {"topic": "testing"},
                },
            ),
            JSONRPCResponse(
                jsonrpc="2.0",
                id=0,
                result={
                    "role": "assistant",
                    "content": {"type": "text", "text": "00000000000000000000000000000456"},
                    "model": "foomodel",
                },
            ),
        ]
    )
    assert patched_client.server_to_client_messages == snapshot(
        [
            JSONRPCRequest(
                jsonrpc="2.0",
                id=0,
                method="sampling/createMessage",
                params={
                    "_meta": {"traceparent": "00-00000000000000000000000000000456-0000000000000def-01"},
                    "messages": [{"role": "user", "content": {"type": "text", "text": "Tell me about testing"}}],
                    "maxTokens": 50,
                },
            ),
            JSONRPCResponse(
                jsonrpc="2.0",
                id=2,
                result={
                    "content": [{"type": "text", "text": "ran sampling"}],
                    "structuredContent": {"result": "ran sampling"},
                    "isError": False,
                },
            ),
        ]
    )
