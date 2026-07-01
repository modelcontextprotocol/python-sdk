"""Tests for `ServerRunner` and the free-function drivers.

The kernel tests run end-to-end over `JSONRPCDispatcher` with a real lowlevel
`Server` as the registry. The `connected_runner` helper starts both sides and
(by default) performs the initialize handshake, so each test exercises only the
behaviour under test. Driver tests (`serve_connection`, `serve_one`,
`aclose_shielded`) follow at the bottom.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, cast

import anyio
import anyio.abc
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    ClientCapabilities,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    ProgressNotificationParams,
    RequestParams,
    SetLevelRequestParams,
    Tool,
)
from mcp_types.version import (
    LATEST_HANDSHAKE_VERSION,
    LATEST_MODERN_VERSION,
    MODERN_PROTOCOL_VERSIONS,
    OLDEST_SUPPORTED_VERSION,
)

import mcp.server.runner
from mcp.server.caching import CacheHint
from mcp.server.connection import Connection, NotifyOnlyOutbound
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.runner import (
    ServerRunner,
    _extract_meta,
    _has_modern_envelope,
    _initialize_after_modern_data,
    _NoServerRequestsDispatchContext,
    aclose_shielded,
    serve_connection,
    serve_dual_era_loop,
    serve_one,
)
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import MessageMetadata, SessionMessage
from mcp.shared.peer import dump_params
from mcp.shared.transport_context import TransportContext

from ..shared.conftest import jsonrpc_pair
from ..shared.test_dispatcher import Recorder, echo_handlers

Ctx = ServerRequestContext[dict[str, Any], Any]


def _initialize_params() -> dict[str, Any]:
    return InitializeRequestParams(
        protocol_version=LATEST_HANDSHAKE_VERSION,
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
    init_options: InitializationOptions | None = None,
    connection: Connection | None = None,
) -> AsyncIterator[tuple[JSONRPCDispatcher[TransportContext], ServerRunner[dict[str, Any]]]]:
    """Yield `(client, runner)` running over an in-memory JSON-RPC dispatcher pair.

    Starts the client (echo handlers) and the server-side dispatcher loop
    (kernel `on_request`/`on_notify` + `aclose_shielded` teardown - the
    `serve_connection` shape) in a task group, wraps the body in
    `anyio.fail_after(5)`, and cancels on exit. When `initialized` is true the
    helper performs the real `initialize` request before yielding, so tests
    start past the init-gate via the public path.

    `connection` defaults to `Connection.for_loop(server_dispatcher)`. Pass a
    factory-built connection (e.g. `Connection.from_envelope(...)`) to exercise
    the born-ready path; the kernel reads it as a fact and is mode-agnostic.
    """
    client, server_d, close = jsonrpc_pair()
    assert isinstance(client, JSONRPCDispatcher) and isinstance(server_d, JSONRPCDispatcher)
    if connection is None:
        connection = Connection.for_loop(server_d)
    runner = ServerRunner(
        server=server,
        connection=connection,
        lifespan_state={},
        init_options=init_options,
    )
    c_req, c_notify = echo_handlers(Recorder())
    body_exc: BaseException | None = None

    async def _drive(*, task_status: anyio.abc.TaskStatus[None]) -> None:
        try:
            await server_d.run(runner.on_request, runner.on_notify, task_status=task_status)
        finally:
            await aclose_shielded(connection)

    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(_drive)
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
    assert runner.connection.protocol_version == LATEST_HANDSHAKE_VERSION
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
    assert ctx.session.protocol_version == runner.connection.protocol_version
    assert ctx.request_id is not None
    assert ctx.protocol_version == LATEST_HANDSHAKE_VERSION


@pytest.mark.anyio
async def test_runner_builds_a_fresh_session_per_request(server: SrvT):
    """`ctx.session` is built per-request from the per-request `DispatchContext`
    and the connection's standalone outbound; it is not connection-scoped."""
    async with connected_runner(server) as (client, _):
        await client.send_raw_request("tools/list", None)
        await client.send_raw_request("tools/list", None)
    assert _seen_ctx[0].session is not _seen_ctx[1].session


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
        "protocol_version": LATEST_HANDSHAKE_VERSION,
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

    async def on_level(ctx: Ctx, params: SetLevelRequestParams) -> None:
        raise NotImplementedError

    server.add_notification_handler("notifications/roots/list_changed", SetLevelRequestParams, on_level)
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

    The in-SDK client always attaches `_meta`, so a middleware rewrites
    `ctx.params` to `None` to model what an external client sends.
    """
    seen: list[PaginatedRequestParams | None] = []

    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        seen.append(params)
        return ListToolsResult(tools=[])

    async def drop_params(ctx: Ctx, call_next: Any) -> Any:
        return await call_next(replace(ctx, params=None) if ctx.method == "tools/list" else ctx)

    server: SrvT = Server(name="s", on_list_tools=list_tools)
    server.middleware.append(drop_params)
    async with connected_runner(server) as (client, _):
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

    async def drop_params(ctx: Ctx, call_next: Any) -> Any:
        return await call_next(replace(ctx, params=None) if ctx.method == "custom/greet" else ctx)

    server: SrvT = Server(name="s")
    server.add_request_handler("custom/greet", GreetParams, greet)
    server.middleware.append(drop_params)
    async with connected_runner(server) as (client, _):
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
async def test_runner_server_middleware_wraps_every_request_including_initialize(server: SrvT):
    seen: list[tuple[str, Any]] = []

    async def ctx_mw(ctx: Ctx, call_next: Any) -> Any:
        seen.append((ctx.method, ctx.params))
        return await call_next(ctx)

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

    async def reject_initialize(ctx: Ctx, call_next: Any) -> Any:
        result = await call_next(ctx)
        if ctx.method == "initialize":
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
    assert not runner.connection.initialized.is_set()


@pytest.mark.anyio
async def test_runner_server_middleware_observes_method_not_found_via_call_next_raise(server: SrvT):
    seen: list[tuple[str, type[BaseException] | None]] = []

    async def observe(ctx: Ctx, call_next: Any) -> Any:
        try:
            return await call_next(ctx)
        except MCPError as e:
            seen.append((ctx.method, type(e)))
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

    async def observe(ctx: Ctx, call_next: Any) -> Any:
        seen.append((ctx.method, ctx.request_id is None))
        return await call_next(ctx)

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
        async def mw(ctx: Ctx, call_next: Any) -> Any:
            order.append(f"{tag}-in")
            result = await call_next(ctx)
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
    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> None:
        return None

    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert result == {}


@pytest.mark.anyio
async def test_runner_handler_returning_error_data_produces_jsonrpc_error(server: SrvT):
    """A handler returning `ErrorData` reaches the client as a JSON-RPC error,
    not a success result, matching `BaseSession._send_response`."""

    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> ErrorData:
        return ErrorData(code=INVALID_PARAMS, message="bad level", data={"got": params.level})

    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)
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

    async def observe(ctx: Ctx, call_next: Any) -> Any:
        try:
            return await call_next(ctx)
        except MCPError as e:
            seen.append(e)
            raise

    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> ErrorData:
        return ErrorData(code=INVALID_PARAMS, message="bad level")

    server.middleware.append(observe)
    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="bad level")
    assert [e.error.message for e in seen] == ["bad level"]


@pytest.mark.anyio
async def test_runner_middleware_returning_error_data_produces_jsonrpc_error(server: SrvT):
    """A middleware that short-circuits with an `ErrorData` return gets the
    same treatment as a handler return: the wire sees a JSON-RPC error."""

    async def short_circuit(ctx: Ctx, call_next: Any) -> Any:
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
async def test_runner_with_born_ready_connection_skips_init_gate(server: SrvT):
    """A `Connection.from_envelope` connection is born ready: the kernel's
    init-gate is open without any handshake. The kernel is mode-agnostic - the
    same `on_request` reads `connection.initialize_accepted` as a fact."""
    born_ready = Connection.from_envelope(LATEST_HANDSHAKE_VERSION, None, None)
    async with connected_runner(server, initialized=False, connection=born_ready) as (client, runner):
        assert runner.connection.initialize_accepted is True
        assert runner.connection.initialized.is_set()
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
async def test_runner_spec_method_with_invalid_params_is_invalid_params_at_the_negotiated_version(server: SrvT):
    async with connected_runner(server) as (client, runner):
        assert runner.connection.protocol_version == LATEST_HANDSHAKE_VERSION
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
async def test_runner_outbound_sieve_drops_configured_cache_hints_at_a_pre_2026_version():
    """A `cache_hints` map fills the typed result before serialization, so the
    same sieve that strips handler-set fields strips configured ones too - a
    2025 client never sees `ttlMs`/`cacheScope`."""

    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    server: SrvT = Server(
        "test-server",
        on_list_tools=list_tools,
        cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")},
    )
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
async def test_on_request_rejects_initialize_at_modern_version_with_method_not_found(server: SrvT):
    """Spec-mandated: `initialize` has no `CLIENT_REQUESTS` row at the modern
    version; kernel dispatch (not the inbound classifier) rejects it."""
    born_ready = Connection.from_envelope(LATEST_MODERN_VERSION, None, None)
    async with connected_runner(server, initialized=False, connection=born_ready) as (client, runner):
        assert runner.connection.protocol_version == LATEST_MODERN_VERSION
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc.value.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_on_request_dispatches_custom_method_registered_via_add_request_handler(server: SrvT):
    """SDK-defined: a method outside `SPEC_CLIENT_METHODS` skips the version
    gate and reaches its registered handler at any negotiated version."""

    async def echo(ctx: Ctx, params: RequestParams) -> dict[str, Any]:
        return {"echoed": True}

    server.add_request_handler("myorg/echo", RequestParams, echo)
    born_ready = Connection.from_envelope(LATEST_MODERN_VERSION, None, None)
    async with connected_runner(server, initialized=False, connection=born_ready) as (client, _):
        result = await client.send_raw_request("myorg/echo", None)
    assert result == {"echoed": True}


@pytest.mark.anyio
async def test_runner_middleware_short_circuit_on_a_wrong_version_spec_method_skips_the_sieve(server: SrvT):
    """A server-tier middleware that returns without calling `call_next` for a
    spec method absent at the negotiated version owns the result shape; the
    outbound sieve has no `(method, version)` row and must not raise."""

    async def short_circuit(ctx: Ctx, call_next: Any) -> Any:
        if ctx.method == "server/discover":
            return {"ok": True}
        return await call_next(ctx)

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
    oldest = OLDEST_SUPPORTED_VERSION
    async with connected_runner(server, initialized=False) as (client, _):
        params = {**_initialize_params(), "protocolVersion": oldest}
        result = await client.send_raw_request("initialize", params)
        assert result["protocolVersion"] == oldest
    async with connected_runner(server, initialized=False) as (client, _):
        params = {**_initialize_params(), "protocolVersion": "1999-01-01"}
        result = await client.send_raw_request("initialize", params)
        assert result["protocolVersion"] == LATEST_HANDSHAKE_VERSION


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


# --- aclose_shielded -----------------------------------------------------------


@pytest.mark.anyio
async def test_aclose_shielded_runs_callbacks_under_outer_cancellation():
    """The shield lets per-connection cleanup run even when the enclosing scope
    is being cancelled."""
    cleaned: list[int] = []
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)

    async def _append() -> None:
        await anyio.sleep(0)
        cleaned.append(1)

    conn.exit_stack.push_async_callback(_append)
    with anyio.CancelScope() as scope:
        scope.cancel()
        await aclose_shielded(conn)
    assert cleaned == [1]


# --- serve_one / serve_connection ---------------------------------------------


@dataclass
class _StubDispatchContext:
    """Minimal `DispatchContext` for `serve_one` driver tests.

    The modern entry hands a per-request context to `serve_one`; this stub
    satisfies the protocol structurally with no real back-channel.
    """

    request_id: int | str | None
    transport: TransportContext = field(default_factory=lambda: TransportContext(kind="direct", can_send_request=False))
    message_metadata: MessageMetadata = None
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)
    can_send_request: bool = False

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        raise NotImplementedError

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        raise NotImplementedError


async def _append_async(dst: list[int], v: int) -> None:
    dst.append(v)


_LIFESPAN: dict[str, Any] = {}


@pytest.mark.anyio
async def test_serve_one_runs_handler_and_returns_result_dict(server: SrvT):
    """The single-exchange driver: builds the kernel, runs `on_request` once,
    returns the agnostic result dict, and tears down `connection.exit_stack`."""
    conn = Connection.from_envelope(LATEST_HANDSHAKE_VERSION, None, None)
    cleaned: list[int] = []
    conn.exit_stack.push_async_callback(_append_async, cleaned, 1)
    result = await serve_one(
        server, _StubDispatchContext(9), "tools/list", None, connection=conn, lifespan_state=_LIFESPAN
    )
    assert result["tools"][0]["name"] == "t"
    assert cleaned == [1]
    ctx = _seen_ctx[0]
    assert ctx.protocol_version == LATEST_HANDSHAKE_VERSION


@pytest.mark.anyio
async def test_serve_one_propagates_error_and_still_closes_exit_stack(server: SrvT):
    """SDK-defined: a kernel-produced error (here `METHOD_NOT_FOUND` for an
    unregistered method) propagates as `MCPError`, and the per-request exit
    stack is closed on the error path too."""
    conn = Connection.from_envelope(LATEST_HANDSHAKE_VERSION, None, None)
    cleaned: list[int] = []
    conn.exit_stack.push_async_callback(_append_async, cleaned, 1)
    with pytest.raises(MCPError) as exc_info:
        await serve_one(
            server, _StubDispatchContext(2), "resources/list", None, connection=conn, lifespan_state=_LIFESPAN
        )
    assert exc_info.value.error.code == METHOD_NOT_FOUND
    assert cleaned == [1]


@pytest.mark.anyio
async def test_serve_one_reads_connection_protocol_version_as_a_fact(server: SrvT):
    """`serve_one` builds the kernel over the entry's `Connection`; the kernel
    reads `connection.protocol_version` for the version gate. A `from_envelope`
    connection at a modern version rejects a method absent there."""
    conn = Connection.from_envelope(LATEST_MODERN_VERSION, None, None)
    with pytest.raises(MCPError) as exc_info:
        await serve_one(
            server,
            _StubDispatchContext(1),
            "logging/setLevel",
            {"level": "info"},
            connection=conn,
            lifespan_state=_LIFESPAN,
        )
    assert exc_info.value.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_serve_connection_drives_dispatcher_loop_and_tears_down(server: SrvT):
    """The loop-mode driver: `serve_connection` builds the kernel, hands
    `on_request`/`on_notify` to `dispatcher.run()`, and `aclose_shielded`s the
    connection on the way out."""
    client, server_d, close = jsonrpc_pair()
    assert isinstance(client, JSONRPCDispatcher) and isinstance(server_d, JSONRPCDispatcher)
    conn = Connection.for_loop(server_d)
    cleaned: list[int] = []
    conn.exit_stack.push_async_callback(_append_async, cleaned, 1)
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(partial(serve_connection, server, server_d, connection=conn, lifespan_state=_LIFESPAN))
        with anyio.fail_after(5):
            await client.send_raw_request("initialize", _initialize_params())
            result = await client.send_raw_request("tools/list", None)
            assert result["tools"][0]["name"] == "t"
            assert cleaned == []
        close()
    assert cleaned == [1]
    assert conn.protocol_version == LATEST_HANDSHAKE_VERSION
    assert conn.client_params is not None


# --- serve_dual_era_loop ----------------------------------------------------


def _modern_envelope(version: str = LATEST_MODERN_VERSION) -> dict[str, Any]:
    return {
        PROTOCOL_VERSION_META_KEY: version,
        CLIENT_INFO_META_KEY: {"name": "test-client", "version": "1.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }


def _modern_params(version: str = LATEST_MODERN_VERSION, **params: Any) -> dict[str, Any]:
    return {**params, "_meta": _modern_envelope(version)}


@asynccontextmanager
async def dual_era_client(server: SrvT) -> AsyncIterator[tuple[JSONRPCDispatcher[TransportContext], Recorder]]:
    """Yield `(client, recorder)` speaking raw frames to a `serve_dual_era_loop` server.

    The driver owns its dispatcher and connection, so unlike `connected_runner`
    the harness hands it bare streams and performs no handshake: each test
    drives the era lock itself.
    """
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)

    def builder(_meta: object) -> TransportContext:
        return TransportContext(kind="jsonrpc", can_send_request=True)

    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send, transport_builder=builder)
    recorder = Recorder()
    c_req, c_notify = echo_handlers(recorder)
    body_exc: BaseException | None = None
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        tg.start_soon(partial(serve_dual_era_loop, server, c2s_recv, s2c_send, lifespan_state=_LIFESPAN))
        try:
            with anyio.fail_after(5):
                yield client, recorder
        except BaseException as e:
            body_exc = e
        tg.cancel_scope.cancel()
    if body_exc is not None:
        raise body_exc


@pytest.mark.anyio
async def test_dual_era_loop_discover_locks_modern_and_serves_envelope_requests(server: SrvT):
    """`server/discover` over the loop returns a DiscoverResult and locks the
    connection modern: envelope-bearing feature requests are then served
    single-exchange, and a later legacy `initialize` is rejected with -32022
    naming the modern versions."""
    async with dual_era_client(server) as (client, _):
        discover = await client.send_raw_request("server/discover", _modern_params())
        assert LATEST_MODERN_VERSION in discover["supportedVersions"]
        assert "tools" in discover["capabilities"]
        result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"][0]["name"] == "t"
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc_info.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert exc_info.value.error.data == {
        "supported": list(MODERN_PROTOCOL_VERSIONS),
        "requested": LATEST_HANDSHAKE_VERSION,
    }


@pytest.mark.anyio
async def test_dual_era_loop_pinned_modern_request_locks_without_a_probe(server: SrvT):
    """A pinned-modern client sends no probe: its first envelope-bearing
    feature request locks the connection modern directly."""
    async with dual_era_client(server) as (client, _):
        result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"][0]["name"] == "t"
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc_info.value.error.code == UNSUPPORTED_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_dual_era_loop_initialize_after_modern_lock_without_a_parseable_version(server: SrvT):
    """An `initialize` with no string protocolVersion still gets the supported
    list in the -32022 data (the typed payload needs a `requested` string)."""
    async with dual_era_client(server) as (client, _):
        await client.send_raw_request("server/discover", _modern_params())
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("initialize", {"capabilities": {}})
    assert exc_info.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert exc_info.value.error.data == {"supported": list(MODERN_PROTOCOL_VERSIONS)}


@pytest.mark.anyio
async def test_dual_era_loop_initialize_locks_legacy_and_rejects_modern_traffic(server: SrvT):
    """After a successful handshake the connection is legacy for its lifetime:
    `server/discover` and envelope-bearing requests are rejected with
    INVALID_REQUEST while plain legacy requests keep working."""
    async with dual_era_client(server) as (client, _):
        init = await client.send_raw_request("initialize", _initialize_params())
        assert init["protocolVersion"] == LATEST_HANDSHAKE_VERSION
        with pytest.raises(MCPError) as discover_exc:
            await client.send_raw_request("server/discover", _modern_params())
        with pytest.raises(MCPError) as envelope_exc:
            await client.send_raw_request("tools/list", _modern_params())
        result = await client.send_raw_request("tools/list", None)
        assert result["tools"][0]["name"] == "t"
    assert discover_exc.value.error.code == INVALID_REQUEST
    assert envelope_exc.value.error.code == INVALID_REQUEST
    assert "locked to the legacy handshake era" in discover_exc.value.error.message


@pytest.mark.anyio
async def test_dual_era_loop_unsupported_modern_version_rejects_without_locking(server: SrvT):
    """A probe at an unknown modern version gets -32022 with the supported
    list, and the rejection does not lock the era: the legacy handshake still
    succeeds afterwards (the released auto clients' retry/fallback contract)."""
    async with dual_era_client(server) as (client, _):
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("server/discover", _modern_params(version="2099-01-01"))
        init = await client.send_raw_request("initialize", _initialize_params())
        assert init["protocolVersion"] == LATEST_HANDSHAKE_VERSION
    assert exc_info.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert exc_info.value.error.data == {
        "supported": list(MODERN_PROTOCOL_VERSIONS),
        "requested": "2099-01-01",
    }


@pytest.mark.anyio
async def test_dual_era_loop_bare_discover_rejects_without_locking(server: SrvT):
    """A `server/discover` with no envelope triple is INVALID_PARAMS - never
    -32022, so a released auto client's code-keyed fallback predicate takes the
    legacy branch - and the connection can still complete the handshake."""
    async with dual_era_client(server) as (client, _):
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("server/discover", None)
        init = await client.send_raw_request("initialize", _initialize_params())
        assert init["protocolVersion"] == LATEST_HANDSHAKE_VERSION
    assert exc_info.value.error.code == INVALID_PARAMS
    assert exc_info.value.error.code != UNSUPPORTED_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_dual_era_loop_ping_before_any_lock_stays_exempt_and_neutral(server: SrvT):
    """A pre-handshake `ping` is answered (the init-gate exemption) and does
    not lock an era: the connection can still go modern."""
    async with dual_era_client(server) as (client, _):
        assert await client.send_raw_request("ping", None) == {}
        result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"][0]["name"] == "t"


@pytest.mark.anyio
async def test_dual_era_loop_modern_request_without_envelope_rejects(server: SrvT):
    """On a modern-locked connection every request is classified: one without
    the envelope triple is INVALID_PARAMS."""
    async with dual_era_client(server) as (client, _):
        await client.send_raw_request("server/discover", _modern_params())
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("tools/list", None)
    assert exc_info.value.error.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_dual_era_loop_rejects_subscriptions_listen_on_modern(server: SrvT):
    """`subscriptions/listen` is rejected before dispatch on the stream-pair
    modern path: the registered handler assumes the HTTP entry's stream
    semantics."""
    async with dual_era_client(server) as (client, _):
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("subscriptions/listen", _modern_params())
    assert exc_info.value.error.code == METHOD_NOT_FOUND
    assert "not served over this transport" in exc_info.value.error.message


@pytest.mark.anyio
async def test_dual_era_loop_modern_notification_dispatches_at_locked_version(server: SrvT):
    """Notifications carry no envelope, so on a modern-locked connection they
    dispatch with the locked protocol version."""
    seen_versions: list[str] = []
    handled = anyio.Event()

    async def on_custom(ctx: Ctx, params: NotificationParams | None) -> None:
        seen_versions.append(ctx.protocol_version)
        handled.set()

    server.add_notification_handler("notifications/custom", NotificationParams, on_custom)
    async with dual_era_client(server) as (client, _):
        await client.send_raw_request("server/discover", _modern_params())
        await client.notify("notifications/custom", None)
        await handled.wait()
    assert seen_versions == [LATEST_MODERN_VERSION]


@pytest.mark.anyio
async def test_dual_era_loop_legacy_notifications_reach_the_loop_runner(server: SrvT):
    """Before/after a legacy lock, notifications flow through the loop runner
    exactly as under `serve_loop`."""
    handled = anyio.Event()

    async def on_custom(ctx: Ctx, params: NotificationParams | None) -> None:
        handled.set()

    server.add_notification_handler("notifications/custom", NotificationParams, on_custom)
    async with dual_era_client(server) as (client, _):
        await client.send_raw_request("initialize", _initialize_params())
        await client.notify("notifications/custom", None)
        await handled.wait()


@pytest.mark.anyio
async def test_dual_era_loop_modern_server_notifications_ride_the_pipe(server: SrvT):
    """A modern handler's standalone notification reaches the client over the
    duplex stream - the notify-only outbound forwards it."""

    async def emit(ctx: Ctx, params: RequestParams | None) -> dict[str, Any]:
        await ctx.session.send_tool_list_changed()
        return {}

    server.add_request_handler("x/emit", RequestParams, emit)
    async with dual_era_client(server) as (client, recorder):
        await client.send_raw_request("x/emit", _modern_params())
        await recorder.notified.wait()
    assert recorder.notifications[0][0] == "notifications/tools/list_changed"


@pytest.mark.anyio
async def test_dual_era_loop_modern_refuses_server_initiated_requests(server: SrvT):
    """A modern handler attempting a server-initiated request gets
    `NoBackChannelError` from the standalone channel: the modern protocol
    forbids the frame, duplex pipe or not."""

    async def wants_roots(ctx: Ctx, params: RequestParams | None) -> dict[str, Any]:
        await ctx.session.list_roots()  # pyright: ignore[reportDeprecated]
        return {}  # pragma: no cover - list_roots raises

    server.add_request_handler("x/roots", RequestParams, wants_roots)
    async with dual_era_client(server) as (client, _):
        with pytest.raises(MCPError) as exc_info:
            await client.send_raw_request("x/roots", _modern_params())
    assert exc_info.value.error.code == INVALID_REQUEST
    assert "no back-channel" in exc_info.value.error.message


def test_has_modern_envelope_requires_the_full_key_triple():
    assert not _has_modern_envelope(None)
    assert not _has_modern_envelope({})
    assert not _has_modern_envelope({"_meta": None})
    assert not _has_modern_envelope({"_meta": {"progressToken": 1}})
    partial_meta = {k: v for k, v in _modern_envelope().items() if k != CLIENT_CAPABILITIES_META_KEY}
    assert not _has_modern_envelope({"_meta": partial_meta})
    assert _has_modern_envelope(_modern_params())


def test_initialize_after_modern_data_arms():
    typed = _initialize_after_modern_data({"protocolVersion": LATEST_HANDSHAKE_VERSION})
    assert typed == {"supported": list(MODERN_PROTOCOL_VERSIONS), "requested": LATEST_HANDSHAKE_VERSION}
    assert _initialize_after_modern_data(None) == {"supported": list(MODERN_PROTOCOL_VERSIONS)}
    assert _initialize_after_modern_data({"protocolVersion": 7}) == {"supported": list(MODERN_PROTOCOL_VERSIONS)}


class _RecordingInnerDctx:
    """Minimal `DispatchContext` double recording delegated calls."""

    def __init__(self) -> None:
        self.transport = TransportContext(kind="jsonrpc", can_send_request=True)
        self.can_send_request = True
        self.request_id = 7
        self.message_metadata = None
        self.cancel_requested = anyio.Event()
        self.notifies: list[str] = []
        self.progresses: list[float] = []

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        raise AssertionError("must never be reached through the denying wrapper")  # pragma: no cover

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        self.notifies.append(method)

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        self.progresses.append(progress)


@pytest.mark.anyio
async def test_no_server_requests_dispatch_context_denies_requests_and_delegates_the_rest():
    inner = _RecordingInnerDctx()
    wrapper = _NoServerRequestsDispatchContext(inner)
    assert wrapper.can_send_request is False
    assert wrapper.transport is inner.transport
    assert wrapper.request_id == 7
    assert wrapper.message_metadata is None
    assert wrapper.cancel_requested is inner.cancel_requested
    with pytest.raises(NoBackChannelError):
        await wrapper.send_raw_request("roots/list", None)
    await wrapper.notify("notifications/progress", None)
    await wrapper.progress(0.5)
    assert inner.notifies == ["notifications/progress"]
    assert inner.progresses == [0.5]


@pytest.mark.anyio
async def test_notify_only_outbound_forwards_notifications_and_refuses_requests():
    inner = _RecordingInnerDctx()
    outbound = NotifyOnlyOutbound(inner)
    await outbound.notify("notifications/tools/list_changed", None)
    assert inner.notifies == ["notifications/tools/list_changed"]
    with pytest.raises(NoBackChannelError):
        await outbound.send_raw_request("ping", None)


@pytest.mark.anyio
async def test_dual_era_client_propagates_body_exception_unwrapped(server: SrvT):
    """The harness re-raises body exceptions as-is, not as `ExceptionGroup`."""
    with pytest.raises(RuntimeError, match="boom"):
        async with dual_era_client(server):
            raise RuntimeError("boom")
