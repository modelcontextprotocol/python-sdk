"""Tests for `ServerRunner`.

End-to-end over `DirectDispatcher` with a real lowlevel `Server` as the
registry. The `connected_runner` helper starts both sides and (by default)
performs the initialize handshake, so each test exercises only the behaviour
under test.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import anyio.lowlevel
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from mcp.server.connection import Connection
from mcp.server.context import Context
from mcp.server.lowlevel.server import Server
from mcp.server.runner import ServerRunner, otel_middleware
from mcp.shared.direct_dispatcher import DirectDispatcher, create_direct_dispatcher_pair
from mcp.shared.dispatcher import DispatchMiddleware
from mcp.shared.exceptions import MCPError
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    Tool,
)

from ..shared.test_dispatcher import Recorder, echo_handlers


def _initialize_params() -> dict[str, Any]:
    return InitializeRequestParams(
        protocol_version=LATEST_PROTOCOL_VERSION,
        capabilities=ClientCapabilities(),
        client_info=Implementation(name="test-client", version="1.0"),
    ).model_dump(by_alias=True, exclude_none=True)


_seen_ctx: list[Context[Any, TransportContext]] = []
SrvT = Server[dict[str, Any]]


@pytest.fixture
def server() -> SrvT:
    """A lowlevel Server with one tools/list handler registered."""
    _seen_ctx.clear()

    async def list_tools(ctx: Any, params: Any) -> Any:
        # ctx is typed `Any` because Server's on_list_tools kwarg expects the
        # legacy ServerRequestContext shape; ServerRunner passes the new
        # `Context`. The transition is intentional — Handler is loosely typed.
        _seen_ctx.append(ctx)
        return {"tools": [Tool(name="t", input_schema={"type": "object"}).model_dump(by_alias=True)]}

    return Server(name="test-server", version="0.0.1", on_list_tools=list_tools)


@asynccontextmanager
async def connected_runner(
    server: SrvT,
    *,
    initialized: bool = True,
    stateless: bool = False,
    has_standalone_channel: bool = True,
    dispatch_middleware: list[DispatchMiddleware] | None = None,
) -> AsyncIterator[tuple[DirectDispatcher, ServerRunner[None, TransportContext]]]:
    """Yield ``(client, runner)`` running over an in-memory dispatcher pair.

    Starts the client (echo handlers) and `runner.run()` in a task group, wraps
    the body in ``anyio.fail_after(5)``, and cancels on exit. When
    ``initialized`` is true the helper performs the real ``initialize`` request
    before yielding, so tests start past the init-gate via the public path.
    """
    client, server_d = create_direct_dispatcher_pair()
    runner = ServerRunner(
        server=server,
        dispatcher=server_d,
        lifespan_state=None,
        has_standalone_channel=has_standalone_channel,
        stateless=stateless,
        dispatch_middleware=dispatch_middleware or [],
    )
    c_req, c_notify = echo_handlers(Recorder())
    body_exc: BaseException | None = None
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(runner.run)
        try:
            with anyio.fail_after(5):
                if initialized:
                    await client.send_raw_request("initialize", _initialize_params())
                yield client, runner
        except BaseException as e:
            # Capture and re-raise outside the task group so test failures
            # surface as the original exception, not an ExceptionGroup wrapper.
            body_exc = e
        client.close()
        server_d.close()
    if body_exc is not None:
        raise body_exc


@pytest.mark.anyio
async def test_connected_runner_propagates_body_exception_unwrapped(server: SrvT):
    """The harness re-raises body exceptions as-is, not as ``ExceptionGroup``."""
    with pytest.raises(RuntimeError, match="boom"):
        async with connected_runner(server):
            raise RuntimeError("boom")


@pytest.mark.anyio
async def test_runner_handles_initialize_and_populates_connection(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, runner):
        result = await client.send_raw_request("initialize", _initialize_params())
    assert result["serverInfo"]["name"] == "test-server"
    assert "tools" in result["capabilities"]
    assert runner.connection.client_info is not None
    assert runner.connection.client_info.name == "test-client"
    assert runner.connection.protocol_version == LATEST_PROTOCOL_VERSION
    assert runner._initialized is True


@pytest.mark.anyio
async def test_runner_gates_requests_before_initialize(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
        assert exc.value.error.code == INVALID_REQUEST
        # ping is exempt from the gate
        assert await client.send_raw_request("ping", None) == {}


@pytest.mark.anyio
async def test_runner_routes_to_handler_and_builds_context(server: SrvT):
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"
    ctx = _seen_ctx[0]
    assert isinstance(ctx, Context)
    assert ctx.lifespan is None
    assert isinstance(ctx.connection, Connection)
    assert ctx.transport.kind == "direct"


@pytest.mark.anyio
async def test_runner_unknown_method_raises_method_not_found(server: SrvT):
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("nonexistent/method", None)
    assert exc.value.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_runner_on_notify_initialized_sets_flag_and_connection_event(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.notify("notifications/initialized", None)
        await runner.connection.initialized.wait()
    assert runner._initialized is True


@pytest.mark.anyio
async def test_runner_on_notify_routes_to_registered_handler(server: SrvT):
    seen: list[tuple[Any, Any]] = []

    async def on_roots_changed(ctx: Any, params: Any) -> None:
        seen.append((ctx, params))

    server._notification_handlers["notifications/roots/list_changed"] = on_roots_changed
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/roots/list_changed", None)
        # DirectDispatcher delivers synchronously; one yield is enough.
        await anyio.lowlevel.checkpoint()
    assert len(seen) == 1
    assert isinstance(seen[0][0], Context)


@pytest.mark.anyio
async def test_runner_on_notify_drops_before_init_and_unknown_methods(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, _):
        await client.notify("notifications/roots/list_changed", None)  # before init: dropped
        await client.notify("notifications/initialized", None)
        await client.notify("notifications/unknown", None)  # no handler: dropped
    # No exception raised; both drops are silent.


@pytest.mark.anyio
async def test_runner_dispatch_middleware_wraps_everything_including_initialize(server: SrvT):
    seen_methods: list[str] = []

    def trace_mw(next_on_request: Any) -> Any:
        async def wrapped(dctx: Any, method: str, params: Any) -> Any:
            seen_methods.append(method)
            return await next_on_request(dctx, method, params)

        return wrapped

    async with connected_runner(server, dispatch_middleware=[trace_mw]) as (client, _):
        await client.send_raw_request("tools/list", None)
    assert seen_methods == ["initialize", "tools/list"]


@pytest.mark.anyio
async def test_runner_server_middleware_wraps_handlers_but_not_initialize(server: SrvT):
    seen_methods: list[str] = []

    async def ctx_mw(ctx: Any, method: str, params: Any, call_next: Any) -> Any:
        seen_methods.append(method)
        return await call_next()

    server.middleware.append(ctx_mw)
    async with connected_runner(server) as (client, _):
        await client.send_raw_request("ping", None)
        await client.send_raw_request("tools/list", None)
    # initialize (sent by the helper) NOT wrapped; ping and tools/list ARE.
    assert seen_methods == ["ping", "tools/list"]


@pytest.mark.anyio
async def test_runner_server_middleware_runs_outermost_first(server: SrvT):
    order: list[str] = []

    def make_mw(tag: str) -> Any:
        async def mw(ctx: Any, method: str, params: Any, call_next: Any) -> Any:
            order.append(f"{tag}-in")
            result = await call_next()
            order.append(f"{tag}-out")
            return result

        return mw

    server.middleware.extend([make_mw("a"), make_mw("b")])
    async with connected_runner(server) as (client, _):
        await client.send_raw_request("tools/list", None)
    assert order == ["a-in", "b-in", "b-out", "a-out"]


@pytest.mark.anyio
async def test_runner_handler_returning_none_yields_empty_result(server: SrvT):
    async def set_level(ctx: Any, params: Any) -> None:
        return None

    server._request_handlers["logging/setLevel"] = set_level
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert result == {}


@pytest.mark.anyio
async def test_runner_handler_returning_unsupported_type_surfaces_as_internal_error(server: SrvT):
    async def bad_return(ctx: Any, params: Any) -> int:
        return 42

    server._request_handlers["tools/list"] = bad_return
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == INTERNAL_ERROR
    assert "int" in exc.value.error.message


@pytest.mark.anyio
async def test_runner_stateless_skips_init_gate(server: SrvT):
    async with connected_runner(server, initialized=False, stateless=True, has_standalone_channel=False) as (client, _):
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"


@pytest.mark.anyio
async def test_otel_middleware_emits_server_span_with_method_and_target(server: SrvT, spans: InMemorySpanExporter):
    async def call_tool(ctx: Any, params: Any) -> dict[str, Any]:
        return {"content": [], "isError": False}

    server._request_handlers["tools/call"] = call_tool
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        result = await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    assert result == {"content": [], "isError": False}
    [span] = spans.get_finished_spans()
    assert span.name == "MCP handle tools/call mytool"
    assert span.kind == SpanKind.SERVER
    assert span.attributes is not None
    assert span.attributes["mcp.method.name"] == "tools/call"
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.anyio
async def test_otel_middleware_extracts_parent_context_from_meta(server: SrvT, spans: InMemorySpanExporter):
    parent_span_id = "b7ad6b7169203331"
    traceparent = f"00-0af7651916cd43dd8448eb211c80319c-{parent_span_id}-01"
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/list", {"_meta": {"traceparent": traceparent}})
    [span] = spans.get_finished_spans()
    assert span.parent is not None
    assert format(span.parent.span_id, "016x") == parent_span_id
    assert span.context is not None
    assert format(span.context.trace_id, "032x") == "0af7651916cd43dd8448eb211c80319c"


@pytest.mark.anyio
async def test_otel_middleware_records_error_status_on_mcp_error(server: SrvT, spans: InMemorySpanExporter):
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("nonexistent/method", None)
        assert exc.value.error.code == METHOD_NOT_FOUND
    [span] = spans.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Method not found: nonexistent/method"
    # MCPError is a protocol-level response, not a crash — no traceback event.
    assert not [e for e in span.events if e.name == "exception"]


@pytest.mark.anyio
async def test_otel_middleware_records_error_status_on_handler_exception(server: SrvT, spans: InMemorySpanExporter):
    async def failing(ctx: Any, params: Any) -> Any:
        raise ValueError("handler blew up")

    server._request_handlers["tools/list"] = failing
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
        assert exc.value.error.code == INTERNAL_ERROR
    [span] = spans.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "handler blew up"
    [event] = [e for e in span.events if e.name == "exception"]
    assert event.attributes is not None
    assert event.attributes["exception.type"] == "ValueError"
