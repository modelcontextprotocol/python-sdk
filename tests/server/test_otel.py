"""Tests for `OpenTelemetryMiddleware` (the context-tier OTel span middleware)."""

from dataclasses import replace
from typing import Any

import anyio
import pytest
from opentelemetry.trace import SpanKind, StatusCode

from mcp.server._otel import OpenTelemetryMiddleware
from mcp.server.context import CallNext
from mcp.server.lowlevel.server import Server
from mcp.server.runner import otel_middleware
from mcp.shared._otel import inject_trace_context
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolRequestParams, ListToolsResult, NotificationParams, PaginatedRequestParams, Tool

from .conftest import SpanCapture
from .test_runner import Ctx, SrvT, connected_runner


@pytest.fixture
def server() -> SrvT:
    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    return Server(name="test-server", version="0.0.1", on_list_tools=list_tools)


async def _ok_tool(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
    return {"content": [], "isError": False}


@pytest.mark.anyio
async def test_emits_server_span_with_method_and_target(server: SrvT, spans: SpanCapture):
    server.add_request_handler("tools/call", CallToolRequestParams, _ok_tool)
    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server) as (client, _):
        spans.clear()
        result = await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    assert result == {"content": [], "isError": False}
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "MCP handle tools/call mytool"
    assert span.attributes is not None
    assert span.attributes["mcp.method.name"] == "tools/call"
    assert isinstance(span.attributes["jsonrpc.request.id"], str)
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.anyio
async def test_notification_span_omits_request_id(server: SrvT, spans: SpanCapture):
    async def on_roots(ctx: Ctx, params: NotificationParams | None) -> None:
        return None

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, on_roots)
    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.notify("notifications/roots/list_changed", None)
        await anyio.wait_all_tasks_blocked()
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "MCP handle notifications/roots/list_changed"
    assert span.attributes is not None
    assert span.attributes["mcp.method.name"] == "notifications/roots/list_changed"
    assert "jsonrpc.request.id" not in span.attributes


@pytest.mark.anyio
async def test_nests_under_ambient_span_when_no_traceparent(server: SrvT, spans: SpanCapture):
    """With no `_meta` on the inbound message (a non-SDK client), the
    context-tier span must parent to the ambient current span (here, the
    dispatch-tier `otel_middleware` span) rather than become an orphan root.
    SDK-defined: SEP-414 only covers the traceparent-present case."""

    def strip_meta(call_next: Any) -> Any:
        # The in-process client always injects `_meta.traceparent`; strip it so
        # both server tiers see the no-carrier path.
        async def wrapped(dctx: Any, method: str, params: dict[str, Any] | None) -> Any:
            stripped = {k: v for k, v in (params or {}).items() if k != "_meta"}
            return await call_next(dctx, method, stripped or None)

        return wrapped

    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server, dispatch_middleware=[strip_meta, otel_middleware]) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/list", None)
    server_spans = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert len(server_spans) == 2
    [outer] = [s for s in server_spans if s.parent is None]
    [inner] = [s for s in server_spans if s.parent is not None]
    assert inner.context is not None and outer.context is not None
    assert inner.parent is not None
    assert inner.context.trace_id == outer.context.trace_id
    assert inner.parent.span_id == outer.context.span_id


@pytest.mark.anyio
async def test_extracts_trace_context_from_meta(server: SrvT, spans: SpanCapture):
    meta: dict[str, Any] = {}
    inject_trace_context(meta)
    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/list", {"_meta": meta})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.parent is not None


@pytest.mark.anyio
async def test_records_error_status_on_mcp_error(server: SrvT, spans: SpanCapture):
    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
        assert exc.value.error.code != 0
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Method not found"
    assert not [e for e in span.events if e.name == "exception"]


@pytest.mark.anyio
async def test_validation_failure_sets_sanitized_status(server: SrvT, spans: SpanCapture):
    server.add_request_handler("tools/call", CallToolRequestParams, _ok_tool)
    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError):
            await client.send_raw_request("tools/call", {"name": 123})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Invalid request parameters"
    assert not span.events


@pytest.mark.anyio
async def test_records_error_status_on_handler_exception(server: SrvT, spans: SpanCapture):
    async def failing(ctx: Ctx, params: PaginatedRequestParams | None) -> Any:
        raise ValueError("handler blew up")

    server.add_request_handler("tools/list", PaginatedRequestParams, failing)
    server.middleware.append(OpenTelemetryMiddleware())
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError):
            await client.send_raw_request("tools/list", None)
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "handler blew up"
    [event] = [e for e in span.events if e.name == "exception"]
    assert event.attributes is not None
    assert event.attributes["exception.type"] == "ValueError"


@pytest.mark.anyio
async def test_passes_rewritten_context_through(server: SrvT, spans: SpanCapture):
    seen_arguments: dict[str, Any] = {}

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
        seen_arguments.update(params.arguments or {})
        return {"content": [], "isError": False}

    async def inject_arg(ctx: Ctx, call_next: CallNext) -> Any:
        assert ctx.params is not None
        arguments = {**ctx.params.get("arguments", {}), "injected": True}
        return await call_next(replace(ctx, params={**ctx.params, "arguments": arguments}))

    server.add_request_handler("tools/call", CallToolRequestParams, call_tool)
    server.middleware.extend([OpenTelemetryMiddleware(), inject_arg])
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {"x": 1}})
    assert seen_arguments == {"x": 1, "injected": True}
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "MCP handle tools/call mytool"
