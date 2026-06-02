"""Tests for `ServerRunner`.

End-to-end over `JSONRPCDispatcher` with a real lowlevel `Server` as the
registry. The `connected_runner` helper starts both sides and (by default)
performs the initialize handshake, so each test exercises only the behaviour
under test.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import anyio
import pytest
from opentelemetry.trace import SpanKind, StatusCode

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.runner import ServerRunner, otel_middleware
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import DispatchMiddleware
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.transport_context import TransportContext
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    ClientCapabilities,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    RequestParams,
    SetLevelRequestParams,
    Tool,
)

from ..shared.conftest import jsonrpc_pair
from ..shared.test_dispatcher import Recorder, echo_handlers
from .conftest import SpanCapture

Ctx = ServerRequestContext[dict[str, Any], Any]


def _initialize_params() -> dict[str, Any]:
    return InitializeRequestParams(
        protocol_version=LATEST_PROTOCOL_VERSION,
        capabilities=ClientCapabilities(),
        client_info=Implementation(name="test-client", version="1.0"),
    ).model_dump(by_alias=True, exclude_none=True)


_seen_ctx: list[Ctx] = []
SrvT = Server[dict[str, Any]]


@pytest.fixture
def server() -> SrvT:
    """A lowlevel Server with one tools/list handler registered."""
    _seen_ctx.clear()

    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        _seen_ctx.append(ctx)
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    return Server(name="test-server", version="0.0.1", on_list_tools=list_tools)


@asynccontextmanager
async def connected_runner(
    server: SrvT,
    *,
    initialized: bool = True,
    stateless: bool = False,
    has_standalone_channel: bool = True,
    init_options: InitializationOptions | None = None,
    session_id: str | None = None,
    dispatch_middleware: list[DispatchMiddleware] | None = None,
) -> AsyncIterator[tuple[JSONRPCDispatcher[TransportContext], ServerRunner[dict[str, Any]]]]:
    """Yield `(client, runner)` running over an in-memory JSON-RPC dispatcher pair.

    Starts the client (echo handlers) and `runner.run()` in a task group, wraps
    the body in `anyio.fail_after(5)`, and cancels on exit. When
    `initialized` is true the helper performs the real `initialize` request
    before yielding, so tests start past the init-gate via the public path.
    """
    client, server_d, close = jsonrpc_pair()
    assert isinstance(client, JSONRPCDispatcher) and isinstance(server_d, JSONRPCDispatcher)
    runner = ServerRunner(
        server=server,
        dispatcher=server_d,
        lifespan_state={},
        has_standalone_channel=has_standalone_channel,
        init_options=init_options,
        session_id=session_id,
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
        close()
    if body_exc is not None:
        raise body_exc


@pytest.mark.anyio
async def test_connected_runner_propagates_body_exception_unwrapped(server: SrvT):
    """The harness re-raises body exceptions as-is, not as `ExceptionGroup`."""
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
        assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
        # ping is exempt from the gate
        assert await client.send_raw_request("ping", None) == {}


@pytest.mark.anyio
async def test_runner_routes_to_handler_and_builds_context(server: SrvT):
    async with connected_runner(server) as (client, runner):
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"
    ctx = _seen_ctx[0]
    assert isinstance(ctx, ServerRequestContext)
    assert ctx.lifespan_context == {}
    assert isinstance(ctx.session, ServerSession)
    assert ctx.session is runner.session
    assert ctx.request_id is not None


@pytest.mark.anyio
async def test_runner_spec_method_with_no_handler_raises_method_not_found(server: SrvT):
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
    assert exc.value.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_runner_non_spec_method_with_no_handler_raises_method_not_found(server: SrvT):
    """Upfront validation is gated to spec methods, so a non-spec method
    skips it and reaches handler lookup."""
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("nonexistent/method", None)
    assert exc.value.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_runner_malformed_params_for_unregistered_spec_method_raises_invalid_params(server: SrvT):
    """A spec method with malformed params is INVALID_PARAMS even with no handler."""
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {"name": 123})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


@pytest.mark.anyio
async def test_runner_on_notify_initialized_sets_flag_and_connection_event(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.notify("notifications/initialized", None)
        await runner.connection.initialized.wait()
    assert runner._initialized is True


@pytest.mark.anyio
async def test_runner_on_notify_routes_to_registered_handler(server: SrvT):
    seen: list[tuple[Any, Any]] = []
    delivered = anyio.Event()

    async def on_roots_changed(ctx: Ctx, params: NotificationParams | None) -> None:
        seen.append((ctx, params))
        if len(seen) == 2:
            delivered.set()

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, on_roots_changed)
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/roots/list_changed", None)
        await client.notify("notifications/roots/list_changed", {})
        await delivered.wait()
    assert isinstance(seen[0][0], ServerRequestContext)
    # Absent wire params reach the handler as None; present-but-empty validates.
    assert seen[0][1] is None
    assert isinstance(seen[1][1], NotificationParams)


@pytest.mark.anyio
async def test_runner_on_notify_handler_exception_is_swallowed_and_logged(
    server: SrvT, caplog: pytest.LogCaptureFixture
):
    """A notification handler crashing must not tear down the connection."""

    async def boom(ctx: Ctx, params: NotificationParams | None) -> None:
        raise RuntimeError("notification handler boom")

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, boom)
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/roots/list_changed", None)
        # Connection still alive: a request after the crashing handler succeeds.
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"
    assert "notification handler for 'notifications/roots/list_changed' raised" in caplog.text


@pytest.mark.anyio
async def test_runner_on_notify_drops_malformed_params(server: SrvT, caplog: pytest.LogCaptureFixture):
    """Malformed notification params are logged and dropped, not raised."""

    async def on_level(ctx: Ctx, params: SetLevelRequestParams) -> None:
        raise NotImplementedError

    server.add_notification_handler("notifications/roots/list_changed", SetLevelRequestParams, on_level)
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/roots/list_changed", {"level": "not-a-level"})
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"
    assert "dropped 'notifications/roots/list_changed': malformed params" in caplog.text


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

    async def ctx_mw(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
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
        async def mw(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
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
    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> None:
        return None

    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert result == {}


@pytest.mark.anyio
async def test_runner_handler_returning_unsupported_type_surfaces_as_error(server: SrvT):
    async def bad_return(ctx: Ctx, params: PaginatedRequestParams | None) -> int:
        return 42

    # cast: deliberately registering a handler with a bad return type to
    # exercise the runtime check; pyright would (correctly) reject it otherwise.
    server.add_request_handler("tools/list", PaginatedRequestParams, cast(Any, bad_return))
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == 0
    assert "int" in exc.value.error.message


@pytest.mark.anyio
async def test_runner_stateless_skips_init_gate(server: SrvT):
    async with connected_runner(server, initialized=False, stateless=True, has_standalone_channel=False) as (client, _):
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"


@pytest.mark.anyio
async def test_server_add_request_handler_routes_custom_method_with_validated_params(server: SrvT):
    """Custom methods outside the spec `ClientRequest` union skip upfront
    validation and route to the registered handler."""

    class GreetParams(RequestParams):
        name: str

    received: list[GreetParams] = []

    async def greet(ctx: Ctx, params: GreetParams) -> dict[str, Any]:
        received.append(params)
        return {"greeting": f"hello {params.name}"}

    server.add_request_handler("custom/greet", GreetParams, greet)
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("custom/greet", {"name": "world"})
    assert result == {"greeting": "hello world"}
    assert isinstance(received[0], GreetParams)
    assert received[0].name == "world"


@pytest.mark.anyio
async def test_runner_initialize_result_reflects_init_options():
    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        raise NotImplementedError

    server: SrvT = Server(name="caps-test", on_list_tools=list_tools, instructions="be nice")
    init_options = server.create_initialization_options(NotificationOptions(tools_changed=True), {"ext": {"k": "v"}})
    async with connected_runner(server, initialized=False, init_options=init_options) as (client, _):
        result = await client.send_raw_request("initialize", _initialize_params())
    assert result["capabilities"]["tools"]["listChanged"] is True
    assert result["capabilities"]["experimental"] == {"ext": {"k": "v"}}
    assert result["serverInfo"]["name"] == "caps-test"
    assert result["instructions"] == "be nice"


@pytest.mark.anyio
async def test_runner_initialize_echoes_supported_version_and_falls_back_to_latest(server: SrvT):
    oldest = SUPPORTED_PROTOCOL_VERSIONS[0]
    async with connected_runner(server, initialized=False) as (client, _):
        params = {**_initialize_params(), "protocolVersion": oldest}
        result = await client.send_raw_request("initialize", params)
        assert result["protocolVersion"] == oldest
    async with connected_runner(server, initialized=False) as (client, _):
        params = {**_initialize_params(), "protocolVersion": "1999-01-01"}
        result = await client.send_raw_request("initialize", params)
        assert result["protocolVersion"] == LATEST_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_otel_middleware_emits_server_span_with_method_and_target(server: SrvT, spans: SpanCapture):
    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> dict[str, Any]:
        return {"content": [], "isError": False}

    server.add_request_handler("tools/call", CallToolRequestParams, call_tool)
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        result = await client.send_raw_request("tools/call", {"name": "mytool", "arguments": {}})
    assert result == {"content": [], "isError": False}
    finished = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    [span] = finished
    assert span.name == "MCP handle tools/call mytool"
    assert span.attributes is not None
    assert span.attributes["mcp.method.name"] == "tools/call"
    assert isinstance(span.attributes["jsonrpc.request.id"], int)
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.anyio
async def test_otel_trace_context_propagates_client_to_server(server: SrvT, spans: SpanCapture):
    """The client dispatcher injects traceparent into `_meta`; the server's
    `otel_middleware` extracts it, so client and server spans share a trace."""
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/list", None)
    [client_span] = [s for s in spans.finished() if s.kind == SpanKind.CLIENT]
    [server_span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert server_span.parent is not None
    assert client_span.context is not None and server_span.context is not None
    assert server_span.parent.span_id == client_span.context.span_id
    assert server_span.context.trace_id == client_span.context.trace_id


@pytest.mark.anyio
async def test_otel_middleware_records_error_status_on_mcp_error(server: SrvT, spans: SpanCapture):
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
        assert exc.value.error.code == METHOD_NOT_FOUND
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Method not found"
    # MCPError is a protocol-level response, not a crash - no traceback event.
    assert not [e for e in span.events if e.name == "exception"]


@pytest.mark.anyio
async def test_otel_middleware_records_error_status_on_handler_exception(server: SrvT, spans: SpanCapture):
    async def failing(ctx: Ctx, params: PaginatedRequestParams | None) -> Any:
        raise ValueError("handler blew up")

    server.add_request_handler("tools/list", PaginatedRequestParams, failing)
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
        assert exc.value.error.code == 0
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "handler blew up"
    [event] = [e for e in span.events if e.name == "exception"]
    assert event.attributes is not None
    assert event.attributes["exception.type"] == "ValueError"


@pytest.mark.anyio
async def test_runner_connection_exit_stack_unwinds_after_run_returns(server: SrvT) -> None:
    """`runner.connection.exit_stack` is closed when the dispatcher loop ends."""
    cleaned: list[int] = []

    async def _append(i: int) -> None:
        cleaned.append(i)

    async with connected_runner(server) as (client, runner):
        for i in (1, 2, 3):
            runner.connection.exit_stack.push_async_callback(_append, i)
        await client.send_raw_request("tools/list", None)
        assert cleaned == []
    assert cleaned == [3, 2, 1]
