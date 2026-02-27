"""Test that OpenTelemetry context is properly injected into _meta."""

# ruff: noqa: E501

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from inline_snapshot import snapshot
from opentelemetry import propagate
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from mcp import Client, ClientSession, types
from mcp.server import MCPServer
from mcp.server.mcpserver.server import Context
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import (
    SamplingMessage,
    TextContent,
)


@pytest.fixture
def server(tracer_provider: TracerProvider) -> MCPServer:
    mcp = MCPServer("test_server", tracer_provider=tracer_provider)

    @mcp.tool()
    async def my_tool() -> str:
        return "hello"

    @mcp.tool()
    async def tool_with_progress(ctx: Context[ServerSession, None]) -> str:
        """Send progress to the client which should parent the client's handling"""
        await ctx.report_progress(progress=0.5, total=1.0)
        return "tool result"

    @mcp.tool()
    async def tool_with_sampling(topic: str, ctx: Context[ServerSession, None]) -> str:
        """Uses LLM sampling to the client which should parent the client's handling"""
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

    @mcp.prompt()
    def my_prompt() -> str:
        return "A test prompt"

    @mcp.resource("file:///home/user/documents/report.pdf")
    def my_resource() -> str:
        return "A test resource"

    @mcp.tool()
    async def slow_tool() -> str:
        import anyio

        await anyio.sleep(1)
        return "I took a while"  # pragma: no cover

    return mcp


@pytest.fixture
async def client(server: MCPServer, tracer_provider: TracerProvider):
    async def sampling_callback(
        context: RequestContext[ClientSession], params: types.CreateMessageRequestParams
    ) -> types.CreateMessageResult:
        return types.CreateMessageResult(
            role="assistant", content=TextContent(type="text", text="hello"), model="foomodel"
        )

    async with Client(server, sampling_callback=sampling_callback, tracer_provider=tracer_provider) as client:
        yield client


@pytest.fixture(autouse=True)
def global_propagator():
    original_propagator = propagate.get_global_textmap()
    propagate.set_global_textmap(TraceContextTextMapPropagator())
    yield
    propagate.set_global_textmap(original_propagator)


@pytest.fixture
def exporter():
    yield InMemorySpanExporter()


@pytest.fixture
def tracer_provider(exporter: InMemorySpanExporter):
    # Generates reproducible sequential IDs for testing
    @dataclass
    class IncrementIdGenerator(IdGenerator):
        next_trace_id: int = -1
        next_span_id: int = -1

        def generate_span_id(self) -> int:
            self.next_span_id += 1
            return self.next_span_id

        def generate_trace_id(self) -> int:
            self.next_trace_id += 1
            return self.next_trace_id

    provider = TracerProvider(id_generator=IncrementIdGenerator())
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    yield provider


def captured_spans(exporter: InMemorySpanExporter):
    return [
        {
            k: v
            for k, v in json.loads(span.to_json(0)).items()
            if k not in ["start_time", "end_time", "events", "resource"]
        }
        for span in exporter.get_finished_spans()
    ]


@pytest.mark.anyio
async def test_initialize_flow(client: Client, exporter: InMemorySpanExporter):
    assert captured_spans(exporter) == snapshot(
        [
            {
                "name": "initialize",
                "context": {
                    "trace_id": "0x00000000000000000000000000000000",
                    "span_id": "0x0000000000000000",
                    "trace_state": "[]",
                },
                "kind": "SpanKind.CLIENT",
                "parent_id": None,
                "status": {"status_code": "UNSET"},
                "attributes": {"mcp.method.name": "initialize", "jsonrpc.request.id": "0"},
                "links": [],
            },
            {
                "name": "notifications/initialized",
                "context": {
                    "trace_id": "0x00000000000000000000000000000001",
                    "span_id": "0x0000000000000001",
                    "trace_state": "[]",
                },
                "kind": "SpanKind.CLIENT",
                "parent_id": None,
                "status": {"status_code": "UNSET"},
                "attributes": {"mcp.method.name": "notifications/initialized"},
                "links": [],
            },
        ]
    )


async def list_tools(client: Client):
    await client.list_tools()


async def call_my_tool(client: Client):
    await client.call_tool("my_tool")


async def call_tool_with_sampling_back_to_client(client: Client):
    await client.call_tool("tool_with_sampling", arguments={"topic": "cats"})


async def call_tool_with_progress_and_custom_span(client: Client):
    async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
        pass

    await client.call_tool("tool_with_progress", progress_callback=progress_callback)


async def get_my_prompt(client: Client):
    await client.get_prompt("my_prompt")


async def read_resource(client: Client):
    await client.read_resource("file:///home/user/documents/report.pdf")


async def call_missing_prompt(client: Client):
    try:
        await client.get_prompt("does_not_exist")
    except MCPError:
        pass


async def call_slow_tool(client: Client):
    try:
        await client.call_tool("slow_tool", read_timeout_seconds=0.01)
    except MCPError:
        pass


@pytest.mark.parametrize(
    "make_call, expect_spans",
    (
        (
            list_tools,
            snapshot(
                [
                    {
                        "name": "tools/list",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {"mcp.method.name": "tools/list", "jsonrpc.request.id": "1"},
                        "links": [],
                    }
                ]
            ),
        ),
        (
            call_my_tool,
            snapshot(
                [
                    {
                        "name": "tools/call my_tool",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {
                            "mcp.method.name": "tools/call",
                            "jsonrpc.request.id": "1",
                            "gen_ai.tool.name": "my_tool",
                            "gen_ai.operation.name": "execute_tool",
                        },
                        "links": [],
                    },
                    {
                        "name": "tools/list",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000003",
                            "span_id": "0x0000000000000003",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {"mcp.method.name": "tools/list", "jsonrpc.request.id": "2"},
                        "links": [],
                    },
                ]
            ),
        ),
        (
            call_tool_with_sampling_back_to_client,
            snapshot(
                [
                    {
                        "name": "sampling/createMessage",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000003",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": "0x0000000000000002",
                        "status": {"status_code": "UNSET"},
                        "attributes": {"mcp.method.name": "sampling/createMessage", "jsonrpc.request.id": "0"},
                        "links": [],
                    },
                    {
                        "name": "tools/call tool_with_sampling",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {
                            "mcp.method.name": "tools/call",
                            "jsonrpc.request.id": "1",
                            "gen_ai.tool.name": "tool_with_sampling",
                            "gen_ai.operation.name": "execute_tool",
                        },
                        "links": [],
                    },
                    {
                        "name": "tools/list",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000003",
                            "span_id": "0x0000000000000004",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {"mcp.method.name": "tools/list", "jsonrpc.request.id": "2"},
                        "links": [],
                    },
                ]
            ),
        ),
        (
            call_tool_with_progress_and_custom_span,
            snapshot(
                [
                    {
                        "name": "notifications/progress",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000003",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": "0x0000000000000002",
                        "status": {"status_code": "UNSET"},
                        "attributes": {"mcp.method.name": "notifications/progress"},
                        "links": [],
                    },
                    {
                        "name": "tools/call tool_with_progress",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {
                            "mcp.method.name": "tools/call",
                            "jsonrpc.request.id": "1",
                            "gen_ai.tool.name": "tool_with_progress",
                            "gen_ai.operation.name": "execute_tool",
                        },
                        "links": [],
                    },
                    {
                        "name": "tools/list",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000003",
                            "span_id": "0x0000000000000004",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {"mcp.method.name": "tools/list", "jsonrpc.request.id": "2"},
                        "links": [],
                    },
                ]
            ),
        ),
        (
            get_my_prompt,
            snapshot(
                [
                    {
                        "name": "prompts/get my_prompt",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {
                            "mcp.method.name": "prompts/get",
                            "jsonrpc.request.id": "1",
                            "gen_ai.prompt.name": "my_prompt",
                        },
                        "links": [],
                    }
                ]
            ),
        ),
        (
            read_resource,
            snapshot(
                [
                    {
                        "name": "resources/read",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {"status_code": "UNSET"},
                        "attributes": {
                            "mcp.method.name": "resources/read",
                            "jsonrpc.request.id": "1",
                            "mcp.resource.uri": "file:///home/user/documents/report.pdf",
                        },
                        "links": [],
                    }
                ]
            ),
        ),
        (
            call_missing_prompt,
            snapshot(
                [
                    {
                        "name": "prompts/get does_not_exist",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {
                            "status_code": "ERROR",
                            "description": "MCPError: Unknown prompt: does_not_exist",
                        },
                        "attributes": {
                            "mcp.method.name": "prompts/get",
                            "jsonrpc.request.id": "1",
                            "gen_ai.prompt.name": "does_not_exist",
                            "error.type": "0",
                            "rpc.response.status_code": "0",
                        },
                        "links": [],
                    }
                ]
            ),
        ),
        (
            call_slow_tool,
            snapshot(
                [
                    {
                        "name": "tools/call slow_tool",
                        "context": {
                            "trace_id": "0x00000000000000000000000000000002",
                            "span_id": "0x0000000000000002",
                            "trace_state": "[]",
                        },
                        "kind": "SpanKind.CLIENT",
                        "parent_id": None,
                        "status": {
                            "status_code": "ERROR",
                            "description": "MCPError: Timed out while waiting for response to CallToolRequest. Waited 0.01 seconds.",
                        },
                        "attributes": {
                            "mcp.method.name": "tools/call",
                            "jsonrpc.request.id": "1",
                            "gen_ai.tool.name": "slow_tool",
                            "gen_ai.operation.name": "execute_tool",
                            "error.type": "timeout",
                        },
                        "links": [],
                    }
                ]
            ),
        ),
    ),
)
@pytest.mark.anyio
async def test_client(
    client: Client,
    exporter: InMemorySpanExporter,
    make_call: Callable[[Client], Awaitable[Any]],
    expect_spans: dict[str, Any],
):
    # Only record spans from the actual make_call()
    exporter.clear()

    await make_call(client)
    assert captured_spans(exporter) == expect_spans
