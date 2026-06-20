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

import mcp.server.runner
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.runner import ServerRunner, _extract_meta, _resolve_protocol_version, otel_middleware
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import DispatchContext, DispatchMiddleware, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata
from mcp.shared.peer import dump_params
from mcp.shared.transport_context import TransportContext
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    CallToolRequestParams,
    ClientCapabilities,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    ProgressNotificationParams,
    RequestParams,
    RequestParamsMeta,
    SetLevelRequestParams,  # pyright: ignore[reportDeprecated]
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
    assert runner.connection.client_params is not None
    assert runner.connection.client_params.client_info.name == "test-client"
    assert runner.connection.protocol_version == LATEST_PROTOCOL_VERSION
    assert runner.connection.initialize_accepted is True


@pytest.mark.anyio
async def test_runner_initialize_opens_gate_but_event_fires_only_after_initialized_notification(server: SrvT):
    """`initialize` commits the gate flag and peer info, but the public
    `connection.initialized` event waits for `notifications/initialized` (the
    point from which the spec permits server-initiated requests)."""
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.send_raw_request("initialize", _initialize_params())
        assert runner.connection.initialize_accepted is True
        assert not runner.connection.initialized.is_set()
        await client.notify("notifications/initialized", None)
        await runner.connection.initialized.wait()


@pytest.mark.anyio
async def test_runner_gates_requests_before_initialize(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
        assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
        # ping is exempt from the gate
        assert await client.send_raw_request("ping", None) == {}


@pytest.mark.anyio
async def test_runner_unknown_method_before_initialize_raises_method_not_found(server: SrvT):
    """An unknown method is METHOD_NOT_FOUND even before initialize: JSON-RPC
    2.0 reserves -32601 for it, and clients probing a server before the
    handshake key off that code. The init gate only applies to methods the
    server actually serves."""
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("x/unknown", None)
        assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="x/unknown")


@pytest.mark.anyio
async def test_runner_spec_method_without_handler_before_initialize_raises_method_not_found(server: SrvT):
    """A spec method the server doesn't serve is METHOD_NOT_FOUND even before
    initialize: -32601 means "not available on this server", so probing
    clients get the same answer in every initialization state (the fixture
    server registers no resources handlers)."""
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
        assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="resources/list")


@pytest.mark.anyio
async def test_runner_custom_method_with_handler_is_still_gated_before_initialize(server: SrvT):
    """A custom-registered method is a known method: before initialize it is
    rejected by the init gate, not answered with METHOD_NOT_FOUND."""

    async def greet(ctx: Ctx, params: RequestParams | None) -> Any:
        raise NotImplementedError  # the gate rejects the request first

    server.add_request_handler("custom/greet", RequestParams, greet)
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("custom/greet", None)
        assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


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
    assert ctx.protocol_version == LATEST_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_runner_spec_method_with_no_handler_raises_method_not_found(server: SrvT):
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
    assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="resources/list")


@pytest.mark.anyio
async def test_runner_non_spec_method_with_no_handler_raises_method_not_found(server: SrvT):
    """Upfront validation is gated to spec methods, so a non-spec method
    skips it and reaches handler lookup."""
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("nonexistent/method", None)
    assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="nonexistent/method")


@pytest.mark.anyio
async def test_runner_malformed_params_for_unregistered_spec_method_raises_invalid_params(server: SrvT):
    """A spec method with malformed params is INVALID_PARAMS even with no handler."""
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {"name": 123})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


@pytest.mark.anyio
async def test_runner_rejects_snake_case_initialize_params(server: SrvT):
    """Inbound wire payloads validate alias-only; Python field names are not
    accepted (`protocol_version` must arrive as `protocolVersion`)."""
    snake = {
        "protocol_version": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "client_info": {"name": "c", "version": "0"},
    }
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", snake)
    assert exc.value.error.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_runner_initialize_with_absent_params_returns_invalid_params_and_stays_alive(server: SrvT):
    """Re-covers what the old `tests/issues/test_malformed_input.py` pinned: a
    malformed `initialize` is rejected and the runner keeps serving."""
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", None)
        assert exc.value.error.code == INVALID_PARAMS
        result = await client.send_raw_request("initialize", _initialize_params())
    assert result["serverInfo"]["name"] == "test-server"


@pytest.mark.anyio
async def test_runner_rejects_snake_case_params_for_custom_handler(server: SrvT):
    """Custom-method handlers (which skip the spec-method gate) still validate
    alias-only at the per-handler boundary."""

    async def handler(ctx: Ctx, params: ProgressNotificationParams) -> dict[str, Any]:
        return {"ok": True}

    server.add_request_handler("custom/progress", ProgressNotificationParams, handler)
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("custom/progress", {"progress_token": 1, "progress": 0.5})
        assert exc.value.error.code == INVALID_PARAMS
        result = await client.send_raw_request("custom/progress", {"progressToken": 1, "progress": 0.5})
    assert result == {"ok": True}


@pytest.mark.anyio
async def test_runner_on_notify_drops_snake_case_params(server: SrvT, caplog: pytest.LogCaptureFixture):
    """Notification params validate alias-only; snake_case is dropped as malformed."""

    async def handler(ctx: Ctx, params: ProgressNotificationParams) -> None:
        raise NotImplementedError

    server.add_notification_handler("notifications/roots/list_changed", ProgressNotificationParams, handler)
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/roots/list_changed", {"progress_token": 1, "progress": 0.5})
        await client.send_raw_request("tools/list", None)
    assert "dropped 'notifications/roots/list_changed': malformed params" in caplog.text


@pytest.mark.anyio
async def test_runner_on_notify_drops_a_spec_notification_absent_at_the_negotiated_version(
    server: SrvT, caplog: pytest.LogCaptureFixture
):
    """`notifications/roots/list_changed` is a client notification but not at
    2026-07-28; the version gate drops it before handler lookup."""
    barrier = anyio.Event()

    async def dropped(ctx: Ctx, params: NotificationParams) -> None:
        raise NotImplementedError  # the version gate drops the notification first

    async def on_barrier(ctx: Ctx, params: NotificationParams) -> None:
        barrier.set()

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, dropped)
    # A custom (non-spec) method bypasses the version gate, so it reaches its
    # handler regardless of which spec notifications exist at the pinned version.
    server.add_notification_handler("custom/barrier", NotificationParams, on_barrier)
    with caplog.at_level("DEBUG", logger="mcp.server.runner"):
        async with connected_runner(server) as (client, runner):
            runner.connection.protocol_version = "2026-07-28"
            await client.notify("notifications/roots/list_changed", None)
            await client.notify("custom/barrier", None)
            await barrier.wait()
    assert "dropped 'notifications/roots/list_changed': not defined at 2026-07-28" in caplog.text


@pytest.mark.anyio
async def test_runner_on_notify_server_direction_spec_method_routes_to_a_registered_handler(server: SrvT):
    """`notifications/message` is a spec method but server-to-client only; on
    a server it is a custom registration (proxy use) and must reach the
    handler, not the client-direction version gate."""
    seen: list[NotificationParams] = []

    async def handler(ctx: Ctx, params: NotificationParams) -> None:
        seen.append(params)

    server.add_notification_handler("notifications/message", NotificationParams, handler)
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/message", {"level": "info", "data": "x"})
        await client.send_raw_request("tools/list", None)
    assert len(seen) == 1


@pytest.mark.anyio
async def test_runner_on_notify_initialized_sets_flag_and_connection_event(server: SrvT):
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.notify("notifications/initialized", None)
        await runner.connection.initialized.wait()
    assert runner.connection.initialize_accepted is True


@pytest.mark.anyio
async def test_runner_on_notify_malformed_initialized_does_not_initialize(
    server: SrvT, caplog: pytest.LogCaptureFixture
):
    """A malformed `notifications/initialized` drops like any other malformed
    notification and leaves the connection uninitialized."""
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.notify("notifications/initialized", {"_meta": 42})
        await anyio.wait_all_tasks_blocked()
        assert runner.connection.initialize_accepted is False
        assert not runner.connection.initialized.is_set()
    assert "dropped 'notifications/initialized': malformed params" in caplog.text


@pytest.mark.anyio
async def test_runner_on_notify_initialized_routes_to_registered_handler_after_state_set(server: SrvT):
    """A handler registered for `notifications/initialized` fires after the
    runner flips the init state, so it observes an initialized connection."""
    seen: list[bool] = []
    delivered = anyio.Event()

    async def on_initialized(ctx: Ctx, params: NotificationParams | None) -> None:
        seen.append(runner.connection.initialize_accepted and runner.connection.initialized.is_set())
        delivered.set()

    server.add_notification_handler("notifications/initialized", NotificationParams, on_initialized)
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.notify("notifications/initialized", {"_meta": {"k": "v"}})
        await delivered.wait()
    assert seen == [True]


def test_server_add_request_handler_rejects_initialize():
    async def handler(ctx: Ctx, params: InitializeRequestParams) -> dict[str, Any]:
        raise NotImplementedError

    server: SrvT = Server(name="s")
    with pytest.raises(ValueError, match="Server.middleware"):
        server.add_request_handler("initialize", InitializeRequestParams, handler)
    assert server.get_request_handler("initialize") is None


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
    # Absent and present-but-empty wire params both validate to the defaults model.
    assert seen[0][1] == NotificationParams()
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

    async def on_level(ctx: Ctx, params: SetLevelRequestParams) -> None:  # pyright: ignore[reportDeprecated]
        raise NotImplementedError

    server.add_notification_handler("notifications/roots/list_changed", SetLevelRequestParams, on_level)  # pyright: ignore[reportDeprecated]
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/roots/list_changed", {"level": "not-a-level"})
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"
    assert "dropped 'notifications/roots/list_changed': malformed params" in caplog.text


@pytest.mark.anyio
async def test_runner_on_notify_drops_absent_params_when_model_requires_them(
    server: SrvT, caplog: pytest.LogCaptureFixture
):
    """A params-less progress notification is dropped, not delivered as None.

    `on_progress` is typed to receive a non-Optional `ProgressNotificationParams`;
    the previous server validated the full notification union and dropped this
    as malformed before dispatch.
    """

    async def on_progress(ctx: Ctx, params: ProgressNotificationParams) -> None:
        raise NotImplementedError

    server.add_notification_handler("notifications/progress", ProgressNotificationParams, on_progress)
    async with connected_runner(server) as (client, _):
        await client.notify("notifications/progress", None)
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"
    assert "dropped 'notifications/progress': malformed params" in caplog.text
    assert "notification handler for" not in caplog.text


@pytest.mark.anyio
async def test_runner_absent_wire_params_reaches_request_handler_as_defaults_model():
    """A request with no `params` member on the wire reaches the handler as
    the params model with its defaults, never `None`.

    The in-SDK client always attaches `_meta`, so a dispatch middleware
    forwards `params=None` to model what an external client sends.
    """
    seen: list[PaginatedRequestParams | None] = []

    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        seen.append(params)
        return ListToolsResult(tools=[])

    def drop_params(next_on_request: OnRequest) -> OnRequest:
        async def wrapped(dctx: DispatchContext[Any], method: str, params: Any) -> dict[str, Any]:
            return await next_on_request(dctx, method, None if method == "tools/list" else params)

        return wrapped

    server: SrvT = Server(name="s", on_list_tools=list_tools)
    async with connected_runner(server, dispatch_middleware=[drop_params]) as (client, _):
        await client.send_raw_request("tools/list", None)
    assert seen == [PaginatedRequestParams()]


@pytest.mark.anyio
async def test_runner_absent_wire_params_for_required_params_custom_method_is_invalid_params():
    """A custom method whose `params_type` has required fields rejects absent
    wire params as INVALID_PARAMS rather than invoking the handler with None."""

    class GreetParams(RequestParams):
        name: str

    async def greet(ctx: Ctx, params: GreetParams) -> dict[str, Any]:
        raise NotImplementedError

    def drop_params(next_on_request: OnRequest) -> OnRequest:
        async def wrapped(dctx: DispatchContext[Any], method: str, params: Any) -> dict[str, Any]:
            return await next_on_request(dctx, method, None if method == "custom/greet" else params)

        return wrapped

    server: SrvT = Server(name="s")
    server.add_request_handler("custom/greet", GreetParams, greet)
    async with connected_runner(server, dispatch_middleware=[drop_params]) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("custom/greet", {"name": "x"})
    assert exc.value.error.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_runner_on_notify_drops_before_init_and_unknown_methods(server: SrvT):
    seen: list[Any] = []

    async def on_roots(ctx: Ctx, params: NotificationParams | None) -> None:
        seen.append(params)

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, on_roots)
    async with connected_runner(server, initialized=False) as (client, _):
        await client.notify("notifications/roots/list_changed", None)  # before init: dropped
        await client.notify("notifications/initialized", None)
        await client.notify("notifications/unknown", None)  # no handler: dropped
        await client.notify("notifications/roots/list_changed", None)  # post-init: delivered
        await anyio.wait_all_tasks_blocked()
    assert seen == [NotificationParams()]  # only the post-init one reached the handler


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
async def test_runner_server_middleware_wraps_every_request_including_initialize(server: SrvT):
    seen: list[tuple[str, Any]] = []

    async def ctx_mw(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        seen.append((method, params))
        return await call_next()

    server.middleware.append(ctx_mw)
    async with connected_runner(server) as (client, _):
        await client.send_raw_request("ping", None)
        await client.send_raw_request("tools/list", {"_meta": {"k": "v"}})
    assert [m for m, _ in seen] == ["initialize", "ping", "tools/list"]
    # params arrive raw (Mapping), not as a validated model
    assert seen[2][1] == {"_meta": {"k": "v"}}


@pytest.mark.anyio
async def test_runner_middleware_raise_after_call_next_on_initialize_leaves_connection_uninitialized(server: SrvT):
    """A middleware failure after `call_next()` on `initialize` reaches the
    client as an error and skips the state commit: the pre-init gate stays
    closed and `connection.initialized` never fires."""

    async def reject_initialize(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        result = await call_next()
        if method == "initialize":
            raise MCPError(code=INTERNAL_ERROR, message="rejected by middleware")
        return result

    server.middleware.append(reject_initialize)
    async with connected_runner(server, initialized=False) as (client, runner):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
        assert exc.value.error.message == "rejected by middleware"
        with pytest.raises(MCPError) as gate_exc:
            await client.send_raw_request("tools/list", None)
        assert gate_exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
        # ping passes through the middleware untouched
        assert await client.send_raw_request("ping", None) == {}
    assert runner.connection.initialize_accepted is False
    assert runner.connection.client_params is None
    assert runner.connection.protocol_version is None
    assert not runner.connection.initialized.is_set()


@pytest.mark.anyio
async def test_runner_server_middleware_observes_method_not_found_via_call_next_raise(server: SrvT):
    seen: list[tuple[str, type[BaseException] | None]] = []

    async def observe(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        try:
            return await call_next()
        except MCPError as e:
            seen.append((method, type(e)))
            raise

    server.middleware.append(observe)
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("nonexistent/method", None)
    assert exc.value.error.code == METHOD_NOT_FOUND
    assert seen == [("nonexistent/method", MCPError)]


@pytest.mark.anyio
async def test_runner_server_middleware_wraps_notifications(server: SrvT):
    """The same chain wraps `_on_notify`: it sees `notifications/initialized`,
    pre-init drops, and registered notification handlers, with
    `ctx.request_id is None`."""
    seen: list[tuple[str, bool]] = []

    async def observe(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        seen.append((method, ctx.request_id is None))
        return await call_next()

    async def on_roots(ctx: Ctx, params: NotificationParams | None) -> None:
        return None

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, on_roots)
    server.middleware.append(observe)
    async with connected_runner(server, initialized=False) as (client, _):
        await client.notify("notifications/roots/list_changed", None)  # pre-init drop, still observed
        await client.notify("notifications/initialized", None)
        await client.notify("notifications/roots/list_changed", None)
        await anyio.wait_all_tasks_blocked()
    assert seen == [
        ("notifications/roots/list_changed", True),
        ("notifications/initialized", True),
        ("notifications/roots/list_changed", True),
    ]


def test_resolve_protocol_version_handshake_committed_value_wins():
    md = ServerMessageMetadata(protocol_version="2025-03-26")
    meta: RequestParamsMeta = {PROTOCOL_VERSION_META_KEY: "2025-03-26"}
    assert _resolve_protocol_version("2025-06-18", meta, md) == "2025-06-18"


def test_resolve_protocol_version_reads_per_request_meta_when_no_handshake():
    md = ServerMessageMetadata(protocol_version="2025-03-26")
    meta: RequestParamsMeta = {PROTOCOL_VERSION_META_KEY: "2025-06-18"}
    assert _resolve_protocol_version(None, meta, md) == "2025-06-18"


def test_resolve_protocol_version_skips_unsupported_meta_value():
    md = ServerMessageMetadata(protocol_version="2025-03-26")
    meta: RequestParamsMeta = {PROTOCOL_VERSION_META_KEY: "1900-01-01"}
    assert _resolve_protocol_version(None, meta, md) == "2025-03-26"


def test_resolve_protocol_version_skips_non_string_meta_value():
    md = ServerMessageMetadata(protocol_version="2025-03-26")
    meta: RequestParamsMeta = {PROTOCOL_VERSION_META_KEY: 42}
    assert _resolve_protocol_version(None, meta, md) == "2025-03-26"


def test_resolve_protocol_version_reads_transport_hint_when_no_handshake_or_meta():
    md = ServerMessageMetadata(protocol_version="2025-06-18")
    assert _resolve_protocol_version(None, None, md) == "2025-06-18"
    assert _resolve_protocol_version(None, {}, md) == "2025-06-18"


def test_resolve_protocol_version_skips_unsupported_transport_hint():
    """The `initialize` params version reaches the metadata unvalidated; surface validation must never see it."""
    md = ServerMessageMetadata(protocol_version="1900-01-01")
    assert _resolve_protocol_version(None, None, md) == "2025-11-25"


def test_resolve_protocol_version_terminal_default_with_no_signals():
    assert _resolve_protocol_version(None, None, None) == "2025-11-25"
    assert _resolve_protocol_version(None, None, ServerMessageMetadata()) == "2025-11-25"
    assert _resolve_protocol_version(None, None, ClientMessageMetadata()) == "2025-11-25"


@pytest.mark.anyio
async def test_runner_ctx_protocol_version_is_terminal_default_on_stateless_in_memory(server: SrvT):
    async with connected_runner(server, initialized=False, stateless=True) as (client, runner):
        await client.send_raw_request("tools/list", None)
    ctx = _seen_ctx[0]
    assert ctx.protocol_version == "2025-11-25"
    assert ctx.session.protocol_version is None
    assert runner.connection.protocol_version is None


@pytest.mark.anyio
async def test_runner_ctx_protocol_version_tracks_per_request_meta_on_stateless(server: SrvT):
    async with connected_runner(server, initialized=False, stateless=True) as (client, _):
        await client.send_raw_request("tools/list", {"_meta": {PROTOCOL_VERSION_META_KEY: "2025-06-18"}})
    assert _seen_ctx[0].protocol_version == "2025-06-18"


def test_extract_meta_returns_none_for_absent_or_malformed():
    """Context construction is independent of `_meta` validity; the params
    validation inside `call_next()` is what surfaces the error."""
    assert _extract_meta(None) is None
    assert _extract_meta({}) is None
    assert _extract_meta({"_meta": "not-a-dict"}) is None
    assert _extract_meta({"_meta": {"progressToken": []}}) is None
    assert _extract_meta({"_meta": {"progressToken": "x", "k": 1}}) == {"progress_token": "x", "k": 1}


def test_extract_meta_round_trips_through_dump_params():
    """Forwarding an inbound `ctx.meta` outbound (`meta=ctx.meta`) re-emits the
    wire key `progressToken`, not the Python field name `_extract_meta`
    validation produced."""
    meta = _extract_meta({"_meta": {"progressToken": 7, "k": 1}})
    assert meta is not None
    assert dump_params(None, dict(meta)) == {"_meta": {"progressToken": 7, "k": 1}}


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
        order.clear()  # drop the wrap of the helper's `initialize`
        await client.send_raw_request("tools/list", None)
    assert order == ["a-in", "b-in", "b-out", "a-out"]


@pytest.mark.anyio
async def test_runner_handler_returning_none_yields_empty_result(server: SrvT):
    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> None:  # pyright: ignore[reportDeprecated]
        return None

    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)  # pyright: ignore[reportDeprecated]
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert result == {}


@pytest.mark.anyio
async def test_runner_handler_returning_error_data_produces_jsonrpc_error(server: SrvT):
    """A handler returning `ErrorData` reaches the client as a JSON-RPC error,
    not a success result, matching `BaseSession._send_response`."""

    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> ErrorData:  # pyright: ignore[reportDeprecated]
        return ErrorData(code=INVALID_PARAMS, message="bad level", data={"got": params.level})

    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)  # pyright: ignore[reportDeprecated]
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="bad level", data={"got": "info"})


@pytest.mark.anyio
async def test_runner_server_middleware_observes_handler_error_data_as_mcp_error(server: SrvT):
    """A handler returning `ErrorData` raises `MCPError` inside `call_next()`,
    so observation middleware records the failure instead of seeing a
    successful-looking `ErrorData` return."""
    seen: list[MCPError] = []

    async def observe(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        try:
            return await call_next()
        except MCPError as e:
            seen.append(e)
            raise

    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> ErrorData:  # pyright: ignore[reportDeprecated]
        return ErrorData(code=INVALID_PARAMS, message="bad level")

    server.middleware.append(observe)
    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)  # pyright: ignore[reportDeprecated]
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="bad level")
    assert [e.error.message for e in seen] == ["bad level"]


@pytest.mark.anyio
async def test_runner_middleware_returning_error_data_produces_jsonrpc_error(server: SrvT):
    """A middleware that short-circuits with an `ErrorData` return gets the
    same treatment as a handler return: the wire sees a JSON-RPC error."""

    async def short_circuit(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        return ErrorData(code=INVALID_PARAMS, message="denied")

    server.middleware.append(short_circuit)
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="denied")


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
async def test_runner_stateless_connection_initialized_event_set_on_construction(server: SrvT):
    """`connection.initialized` mirrors the gate flag in stateless mode so
    `await connection.initialized.wait()` does not hang when no handshake
    arrives."""
    async with connected_runner(server, initialized=False, stateless=True, has_standalone_channel=False) as (_, runner):
        assert runner.connection.initialize_accepted is True
        assert runner.connection.initialized.is_set()
        await runner.connection.initialized.wait()


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
async def test_runner_spec_method_with_invalid_params_is_invalid_params_at_the_negotiated_version(server: SrvT):
    async with connected_runner(server) as (client, runner):
        assert runner.connection.protocol_version == LATEST_PROTOCOL_VERSION
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {"name": 42})
    assert exc.value.error.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_runner_handler_returning_malformed_dict_for_spec_method_is_internal_error(server: SrvT):
    async def bad_result(ctx: Ctx, params: PaginatedRequestParams | None) -> dict[str, Any]:
        return {"tools": 42}

    server.add_request_handler("tools/list", PaginatedRequestParams, bad_result)
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Handler returned an invalid result"
    # Result body must not reach the client; detail belongs in the server log.
    assert exc.value.error.data is None


@pytest.mark.anyio
async def test_runner_handler_returning_typed_monolith_result_passes_outbound_validation(server: SrvT):
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"


@pytest.mark.anyio
async def test_runner_outbound_sieve_drops_2026_only_result_keys_at_a_pre_2026_version(server: SrvT):
    """The handler's `resultType`/`ttlMs`/`cacheScope` are sieved out so a 2025
    client sees only schema fields."""

    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})], ttl_ms=5, cache_scope="public")

    server.add_request_handler("tools/list", PaginatedRequestParams, list_tools)
    async with connected_runner(server) as (client, runner):
        assert runner.connection.protocol_version == "2025-11-25"
        result = await client.send_raw_request("tools/list", None)
    assert result == {"tools": [{"name": "t", "inputSchema": {"type": "object"}}]}


@pytest.mark.anyio
async def test_runner_server_direction_spec_method_routes_to_a_registered_handler(server: SrvT):
    """`roots/list` is a spec method but server-to-client only; on a server it
    is a custom registration (proxy use) and must reach the handler, not the
    client-direction version gate."""

    async def list_roots(ctx: Ctx, params: RequestParams) -> dict[str, Any]:
        return {"roots": [{"uri": "file:///workspace"}]}

    server.add_request_handler("roots/list", RequestParams, list_roots)
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("roots/list", None)
    assert result == {"roots": [{"uri": "file:///workspace"}]}


@pytest.mark.anyio
async def test_runner_spec_method_absent_at_the_negotiated_version_is_method_not_found(server: SrvT):
    """`server/discover` is a spec method (in `MONOLITH_REQUESTS`) but only at
    2026-07-28; on a 2025 session it must be METHOD_NOT_FOUND even with a
    registered handler."""

    async def discover(ctx: Ctx, params: RequestParams) -> Any:
        raise NotImplementedError  # the version gate rejects the request first

    server.add_request_handler("server/discover", RequestParams, discover)
    async with connected_runner(server) as (client, runner):
        assert runner.connection.protocol_version == "2025-11-25"
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("server/discover", None)
    assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="server/discover")


@pytest.mark.anyio
async def test_runner_middleware_short_circuit_on_a_wrong_version_spec_method_skips_the_sieve(server: SrvT):
    """A server-tier middleware that returns without calling `call_next` for a
    spec method absent at the negotiated version owns the result shape; the
    outbound sieve has no `(method, version)` row and must not raise."""

    async def short_circuit(ctx: Ctx, method: str, params: Any, call_next: Any) -> Any:
        if method == "server/discover":
            return {"ok": True}
        return await call_next()

    server.middleware.append(short_circuit)
    async with connected_runner(server) as (client, runner):
        assert runner.connection.protocol_version == "2025-11-25"
        result = await client.send_raw_request("server/discover", None)
    assert result == {"ok": True}


@pytest.mark.anyio
async def test_runner_custom_method_result_is_not_surface_validated(server: SrvT):
    """No `SERVER_RESULTS` row for a custom method, so its result reaches the client as-is."""

    async def custom(ctx: Ctx, params: RequestParams) -> dict[str, Any]:
        return {"anything": "goes"}

    server.add_request_handler("custom/greet", RequestParams, custom)
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("custom/greet", None)
    assert result == {"anything": "goes"}


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
    assert isinstance(span.attributes["jsonrpc.request.id"], str)
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
    assert client_span.attributes is not None and server_span.attributes is not None
    assert client_span.attributes["jsonrpc.request.id"] == server_span.attributes["jsonrpc.request.id"]


@pytest.mark.anyio
async def test_otel_middleware_malformed_traceparent_degrades_to_no_parent(server: SrvT, spans: SpanCapture):
    """A non-string traceparent in `_meta` must not fail the request; the
    server span simply gets no parent."""

    def break_traceparent(next_on_request: OnRequest) -> OnRequest:
        async def wrapped(dctx: DispatchContext[Any], method: str, params: Any) -> dict[str, Any]:
            mangled = {"_meta": {"traceparent": 123}} if method == "tools/list" else params
            return await next_on_request(dctx, method, mangled)

        return wrapped

    async with connected_runner(server, dispatch_middleware=[break_traceparent, otel_middleware]) as (client, _):
        spans.clear()
        await client.send_raw_request("tools/list", None)
    [server_span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert server_span.parent is None


@pytest.mark.anyio
async def test_otel_middleware_validation_failure_sets_sanitized_status(server: SrvT, spans: SpanCapture):
    """Malformed params set the sanitized wire message as span status and do
    not record the pydantic exception (it carries client input)."""
    async with connected_runner(server, dispatch_middleware=[otel_middleware]) as (client, _):
        spans.clear()
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {"name": 123})
    assert exc.value.error.code == INVALID_PARAMS
    [span] = [s for s in spans.finished() if s.kind == SpanKind.SERVER]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "Invalid request parameters"
    assert not span.events


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


@pytest.mark.anyio
async def test_runner_exit_stack_cleanup_exception_is_logged_not_propagated(
    server: SrvT, caplog: pytest.LogCaptureFixture
) -> None:
    """A raising cleanup callback is caught and logged; `run()` exits cleanly."""
    cleaned: list[str] = []

    async def _ok() -> None:
        cleaned.append("ok")

    async def _boom() -> None:
        raise RuntimeError("cleanup failed")

    async with connected_runner(server) as (client, runner):
        runner.connection.exit_stack.push_async_callback(_ok)
        runner.connection.exit_stack.push_async_callback(_boom)
        await client.send_raw_request("tools/list", None)
    assert cleaned == ["ok"]
    assert "connection exit_stack cleanup raised" in caplog.text


@pytest.mark.anyio
async def test_runner_exit_stack_blocking_cleanup_abandoned_after_grace(
    server: SrvT, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A cleanup callback that never returns is abandoned once the grace period
    elapses: `run()` exits, later callbacks in the unwind are cancelled at
    their first checkpoint, and a warning is logged. Grace 0 means the deadline
    is already expired on entry, so the abandonment is immediate."""
    monkeypatch.setattr(mcp.server.runner, "_EXIT_STACK_CLOSE_TIMEOUT", 0)
    ran: list[str] = []
    release = anyio.Event()

    async def _abandoned() -> None:
        # LIFO unwind: pushed first, so it runs after the blocker. By then the
        # deadline has fired, so this checkpoint raises and the line below is
        # unreachable (if abandonment broke, the missing warning fails the
        # caplog assert).
        await anyio.sleep(0)
        raise NotImplementedError

    async def _blocker() -> None:
        ran.append("blocker started")
        await release.wait()
        raise NotImplementedError

    async with connected_runner(server) as (client, runner):
        runner.connection.exit_stack.push_async_callback(_abandoned)
        runner.connection.exit_stack.push_async_callback(_blocker)
        await client.send_raw_request("tools/list", None)
    assert ran == ["blocker started"]
    assert "abandoning remaining callbacks" in caplog.text


@pytest.mark.anyio
async def test_runner_exit_stack_fast_cleanup_completes_within_grace(
    server: SrvT, caplog: pytest.LogCaptureFixture
) -> None:
    """Well-behaved cleanup callbacks run to completion under the bounded
    unwind and no abandonment warning is logged. Uses the production grace;
    the deadline never delays a fast unwind, it only bounds a hung one."""
    cleaned: list[int] = []

    async def _append(i: int) -> None:
        await anyio.sleep(0)
        cleaned.append(i)

    async with connected_runner(server) as (client, runner):
        for i in (1, 2):
            runner.connection.exit_stack.push_async_callback(_append, i)
        await client.send_raw_request("tools/list", None)
    assert cleaned == [2, 1]
    assert "abandoning remaining callbacks" not in caplog.text
