"""Tests for `OpenTelemetryMiddleware` (the context-tier OTel span middleware).

Every `Server` ships `OpenTelemetryMiddleware` at the head of `Server.middleware`,
so these tests assert against the default-configured server rather than appending
the middleware by hand.
"""

from dataclasses import replace
from typing import Any

import anyio
import pytest
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    GetPromptRequestParams,
    GetPromptResult,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    Tool,
)
from opentelemetry.trace import SpanKind, StatusCode

from mcp.server._otel import OpenTelemetryMiddleware
from mcp.server.context import CallNext
from mcp.server.lowlevel.server import Server
from mcp.shared._otel import inject_trace_context, otel_span
from mcp.shared.exceptions import MCPError

from .conftest import SpanCapture
from .test_runner import Ctx, SrvT, connected_runner


@pytest.fixture
def server() -> SrvT:
    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    return Server(name="test-server", version="0.0.1", on_list_tools=list_tools)


async def _ok_tool(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
    return {"content": [], "isError": False}


def test_server_ships_opentelemetry_middleware_by_default() -> None:
    server = Server(name="test-server", version="0.0.1")
    assert any(isinstance(m, OpenTelemetryMiddleware) for m in server.middleware)


@pytest.mark.anyio
async def test_emits_server_span_with_method_and_target(server: SrvT, spans: SpanCapture):
    server.add_request_handler("tools/call", CallToolRequestParams, _ok_tool)
    async with connected_runner(server) as (client, _):
        spans.clear()
        result = await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    assert result == {"content": [], "isError": False}
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "tools/call mytool"
    assert span.attributes is not None
    assert span.attributes["mcp.method.name"] == "tools/call"
    assert span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert span.attributes["gen_ai.tool.name"] == "mytool"
    assert isinstance(span.attributes["jsonrpc.request.id"], str)
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.anyio
async def test_tool_error_dict_result_sets_error_type(server: SrvT, spans: SpanCapture):
    async def err_tool(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
        return {"content": [], "isError": True}

    server.add_request_handler("tools/call", CallToolRequestParams, err_tool)
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.attributes is not None
    assert span.attributes["error.type"] == "tool_error"
    assert span.status.status_code == StatusCode.ERROR


@pytest.mark.anyio
async def test_tool_error_model_result_sets_error_type(server: SrvT, spans: SpanCapture):
    async def err_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[], is_error=True)

    server.add_request_handler("tools/call", CallToolRequestParams, err_tool)
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.attributes is not None
    assert span.attributes["error.type"] == "tool_error"
    assert span.status.status_code == StatusCode.ERROR


@pytest.mark.anyio
async def test_snake_case_dict_result_is_not_a_tool_error(server: SrvT, spans: SpanCapture):
    # `is_error` is alias-only on the wire, so serialization drops it; the result reaches the
    # client as a success and the span must not contradict that.
    async def err_tool(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
        return {"content": [], "is_error": True}

    server.add_request_handler("tools/call", CallToolRequestParams, err_tool)
    async with connected_runner(server) as (client, _):
        spans.clear()
        result = await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    assert result == {"content": []}
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.attributes is not None
    assert "error.type" not in span.attributes
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.anyio
async def test_named_non_tool_prompt_method_omits_gen_ai_attrs(server: SrvT, spans: SpanCapture):
    async def custom(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
        return {"content": [], "isError": False}

    server.add_request_handler("custom/op", CallToolRequestParams, custom)
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("custom/op", {"name": "thing", "arguments": {}})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "custom/op thing"
    assert span.attributes is not None
    assert "gen_ai.operation.name" not in span.attributes
    assert "gen_ai.tool.name" not in span.attributes
    assert "gen_ai.prompt.name" not in span.attributes


@pytest.mark.anyio
async def test_prompt_get_sets_prompt_name(server: SrvT, spans: SpanCapture):
    async def get_prompt(ctx: Ctx, params: GetPromptRequestParams) -> GetPromptResult:
        return GetPromptResult(messages=[])

    server.add_request_handler("prompts/get", GetPromptRequestParams, get_prompt)
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("prompts/get", {"name": "myprompt"})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "prompts/get myprompt"
    assert span.attributes is not None
    assert span.attributes["gen_ai.prompt.name"] == "myprompt"
    assert "gen_ai.operation.name" not in span.attributes


@pytest.mark.anyio
async def test_notification_span_omits_request_id(server: SrvT, spans: SpanCapture):
    async def on_roots(ctx: Ctx, params: NotificationParams | None) -> None:
        return None

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, on_roots)
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.notify("notifications/roots/list_changed", None)
        await anyio.wait_all_tasks_blocked()
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "notifications/roots/list_changed"
    assert span.attributes is not None
    assert span.attributes["mcp.method.name"] == "notifications/roots/list_changed"
    assert "jsonrpc.request.id" not in span.attributes


def _ambient_span(call_next: Any) -> Any:
    """Dispatch-tier wrapper that opens an ambient SERVER span around the whole
    request, so the context-tier span has a current span to nest under when the
    inbound message carries no traceparent."""

    async def wrapped(dctx: Any, method: str, params: dict[str, Any] | None) -> Any:
        with otel_span("ambient", kind=SpanKind.SERVER):
            return await call_next(dctx, method, params)

    return wrapped


@pytest.mark.anyio
async def test_nests_under_ambient_span_when_no_traceparent(server: SrvT, spans: SpanCapture):
    """With no `_meta` on the inbound message (a non-SDK client), the span must
    parent to the ambient current span rather than become an orphan root.
    SDK-defined: SEP-414 only covers the traceparent-present case."""

    def strip_meta(call_next: Any) -> Any:
        # The in-process client always injects `_meta.traceparent`; strip it so
        # the span sees the no-carrier path.
        async def wrapped(dctx: Any, method: str, params: dict[str, Any] | None) -> Any:
            stripped = {k: v for k, v in (params or {}).items() if k != "_meta"}
            return await call_next(dctx, method, stripped or None)

        return wrapped

    async with connected_runner(server, dispatch_middleware=[_ambient_span, strip_meta]) as (client, _):
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
async def test_nests_under_ambient_span_when_meta_lacks_traceparent(server: SrvT, spans: SpanCapture):
    """`_meta` is present but carries no `traceparent` (e.g. only a
    `progressToken`). `extract()` would yield an empty Context here, which
    would orphan the span; the middleware must fall through to ambient
    parenting just as if `_meta` were absent."""

    def replace_meta(call_next: Any) -> Any:
        async def wrapped(dctx: Any, method: str, params: dict[str, Any] | None) -> Any:
            rewritten = {**(params or {}), "_meta": {"progressToken": "tok"}}
            return await call_next(dctx, method, rewritten)

        return wrapped

    async with connected_runner(server, dispatch_middleware=[_ambient_span, replace_meta]) as (client, _):
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
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/list", {"_meta": meta})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.parent is not None


@pytest.mark.anyio
async def test_records_error_status_on_mcp_error(server: SrvT, spans: SpanCapture):
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
        assert exc.value.error.code != 0
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Method not found"
    assert span.attributes is not None
    assert span.attributes["error.type"] == str(exc.value.error.code)
    assert span.attributes["rpc.response.status_code"] == str(exc.value.error.code)
    assert not [e for e in span.events if e.name == "exception"]


@pytest.mark.anyio
async def test_validation_failure_sets_sanitized_status(server: SrvT, spans: SpanCapture):
    server.add_request_handler("tools/call", CallToolRequestParams, _ok_tool)
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError):
            await client.send_raw_request("tools/call", {"name": 123})
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Invalid request parameters"
    assert span.attributes is not None
    assert span.attributes["error.type"] == str(INVALID_PARAMS)
    assert span.attributes["rpc.response.status_code"] == str(INVALID_PARAMS)
    assert span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert "gen_ai.tool.name" not in span.attributes
    assert not span.events


@pytest.mark.anyio
async def test_records_error_status_on_handler_exception(server: SrvT, spans: SpanCapture):
    async def failing(ctx: Ctx, params: PaginatedRequestParams | None) -> Any:
        raise ValueError("handler blew up")

    server.add_request_handler("tools/list", PaginatedRequestParams, failing)
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError):
            await client.send_raw_request("tools/list", None)
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "handler blew up"
    assert span.attributes is not None
    assert span.attributes["error.type"] == "ValueError"
    [event] = [e for e in span.events if e.name == "exception"]
    assert event.attributes is not None
    assert event.attributes["exception.type"] == "ValueError"


@pytest.mark.anyio
async def test_records_error_status_on_malformed_spec_result(server: SrvT, spans: SpanCapture):
    """Result serialization runs inside the span, so a handler returning a
    malformed dict for a spec method (INTERNAL_ERROR on the wire) is recorded
    on the span rather than closing it as a success."""

    async def bad_result(ctx: Ctx, params: PaginatedRequestParams | None) -> dict[str, Any]:
        return {"tools": 42}

    server.add_request_handler("tools/list", PaginatedRequestParams, bad_result)
    async with connected_runner(server) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
        assert exc.value.error.code == INTERNAL_ERROR
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == str(INTERNAL_ERROR)
    assert span.attributes["rpc.response.status_code"] == str(INTERNAL_ERROR)


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
    server.middleware.append(inject_arg)
    async with connected_runner(server) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {"x": 1}})
    assert seen_arguments == {"x": 1, "injected": True}
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.name == "tools/call mytool"
