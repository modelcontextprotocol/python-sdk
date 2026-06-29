"""Tests for `ServerRunner` and the free-function drivers.

Kernel tests run end-to-end over `JSONRPCDispatcher` with a real lowlevel `Server`;
`connected_runner` starts both sides and (by default) performs the initialize handshake.
Driver tests (`serve_connection`, `serve_one`, `aclose_shielded`) follow at the bottom.
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
    INTERNAL_ERROR,
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
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
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION, OLDEST_SUPPORTED_VERSION

import mcp.server.runner
from mcp.server.caching import CacheHint
from mcp.server.connection import Connection
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.runner import (
    ServerRunner,
    _extract_meta,
    aclose_shielded,
    serve_connection,
    serve_one,
)
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import MessageMetadata
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

    Mirrors the `serve_connection` shape (kernel handlers + `aclose_shielded` teardown). When
    `initialized` is true, the real `initialize` request runs before yielding. `connection`
    defaults to `Connection.for_loop`; pass `Connection.from_envelope(...)` for the born-ready path.
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
            # Re-raise outside the task group so failures surface unwrapped, not as an ExceptionGroup.
            body_exc = e
        close()
    if body_exc is not None:
        raise body_exc


@pytest.mark.anyio
async def test_connected_runner_propagates_body_exception_unwrapped(server: SrvT):
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
    """The event fires at `notifications/initialized`, the point the spec permits server-initiated requests."""
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
    """JSON-RPC 2.0 reserves -32601 for unknown methods; the init gate only applies to methods the server serves."""
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("x/unknown", None)
        assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="x/unknown")


@pytest.mark.anyio
async def test_runner_spec_method_without_handler_before_initialize_raises_method_not_found(server: SrvT):
    """-32601 means "not available on this server", so probing clients get the same answer in every init state."""
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("resources/list", None)
        assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="resources/list")


@pytest.mark.anyio
async def test_runner_custom_method_with_handler_is_still_gated_before_initialize(server: SrvT):
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
    """Upfront validation only covers spec methods; a non-spec method goes straight to handler lookup."""
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("nonexistent/method", None)
    assert exc.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="nonexistent/method")


@pytest.mark.anyio
async def test_runner_malformed_params_for_unregistered_spec_method_raises_invalid_params(server: SrvT):
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {"name": 123})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


@pytest.mark.anyio
async def test_runner_rejects_snake_case_initialize_params(server: SrvT):
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
    """Re-covers old `tests/issues/test_malformed_input.py`: the runner keeps serving after a malformed initialize."""
    async with connected_runner(server, initialized=False) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", None)
        assert exc.value.error.code == INVALID_PARAMS
        result = await client.send_raw_request("initialize", _initialize_params())
    assert result["serverInfo"]["name"] == "test-server"


@pytest.mark.anyio
async def test_runner_rejects_snake_case_params_for_custom_handler(server: SrvT):
    """Custom handlers skip the spec-method gate but still validate alias-only at the per-handler boundary."""

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
    """`notifications/roots/list_changed` is a client notification but absent at 2026-07-28."""
    barrier = anyio.Event()

    async def dropped(ctx: Ctx, params: NotificationParams) -> None:
        raise NotImplementedError  # the version gate drops the notification first

    async def on_barrier(ctx: Ctx, params: NotificationParams) -> None:
        barrier.set()

    server.add_notification_handler("notifications/roots/list_changed", NotificationParams, dropped)
    # Custom (non-spec) methods bypass the version gate, so the barrier handler still runs.
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
    """`notifications/message` is server-to-client; on a server it is a custom registration (proxy use)."""
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
    async with connected_runner(server, initialized=False) as (client, runner):
        await client.notify("notifications/initialized", {"_meta": 42})
        await anyio.wait_all_tasks_blocked()
        assert runner.connection.initialize_accepted is False
        assert not runner.connection.initialized.is_set()
    assert "dropped 'notifications/initialized': malformed params" in caplog.text


@pytest.mark.anyio
async def test_runner_on_notify_initialized_routes_to_registered_handler_after_state_set(server: SrvT):
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
    """Matches the previous server, which validated the full notification union and dropped this before dispatch."""

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
    """The in-SDK client always attaches `_meta`, so a middleware models an external client's bare request."""
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
    assert seen == [NotificationParams()]


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
    """The error reaches the client and the state commit is skipped: the pre-init gate stays closed."""

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
    """Malformed `_meta` yields None; the params validation inside `call_next()` is what surfaces the error."""
    assert _extract_meta(None) is None
    assert _extract_meta({}) is None
    assert _extract_meta({"_meta": "not-a-dict"}) is None
    assert _extract_meta({"_meta": {"progressToken": []}}) is None
    assert _extract_meta({"_meta": {"progressToken": "x", "k": 1}}) == {"progress_token": "x", "k": 1}


def test_extract_meta_round_trips_through_dump_params():
    """Forwarding inbound `ctx.meta` outbound re-emits the wire key `progressToken`, not the Python field name."""
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
    """Matches `BaseSession._send_response`: an `ErrorData` return becomes a JSON-RPC error, not a result."""

    async def set_level(ctx: Ctx, params: SetLevelRequestParams) -> ErrorData:
        return ErrorData(code=INVALID_PARAMS, message="bad level", data={"got": params.level})

    server.add_request_handler("logging/setLevel", SetLevelRequestParams, set_level)
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("logging/setLevel", {"level": "info"})
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="bad level", data={"got": "info"})


@pytest.mark.anyio
async def test_runner_server_middleware_observes_handler_error_data_as_mcp_error(server: SrvT):
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

    # cast: deliberately bad return type to exercise the runtime check; pyright would reject it otherwise.
    server.add_request_handler("tools/list", PaginatedRequestParams, cast(Any, bad_return))
    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == 0
    assert "int" in exc.value.error.message


@pytest.mark.anyio
async def test_runner_with_born_ready_connection_skips_init_gate(server: SrvT):
    """The kernel is mode-agnostic: it reads `connection.initialize_accepted` as a fact, with no handshake."""
    born_ready = Connection.from_envelope(LATEST_HANDSHAKE_VERSION, None, None)
    async with connected_runner(server, initialized=False, connection=born_ready) as (client, runner):
        assert runner.connection.initialize_accepted is True
        assert runner.connection.initialized.is_set()
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"


@pytest.mark.anyio
async def test_server_add_request_handler_routes_custom_method_with_validated_params(server: SrvT):
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
    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})], ttl_ms=5, cache_scope="public")

    server.add_request_handler("tools/list", PaginatedRequestParams, list_tools)
    async with connected_runner(server) as (client, runner):
        assert runner.connection.protocol_version == "2025-11-25"
        result = await client.send_raw_request("tools/list", None)
    assert result == {"tools": [{"name": "t", "inputSchema": {"type": "object"}}]}


@pytest.mark.anyio
async def test_runner_outbound_sieve_drops_configured_cache_hints_at_a_pre_2026_version():
    """`cache_hints` fills the typed result before serialization, so the same sieve strips configured fields too."""

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
    """`roots/list` is server-to-client; on a server it is a custom registration (proxy use)."""

    async def list_roots(ctx: Ctx, params: RequestParams) -> dict[str, Any]:
        return {"roots": [{"uri": "file:///workspace"}]}

    server.add_request_handler("roots/list", RequestParams, list_roots)
    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("roots/list", None)
    assert result == {"roots": [{"uri": "file:///workspace"}]}


@pytest.mark.anyio
async def test_runner_spec_method_absent_at_the_negotiated_version_is_method_not_found(server: SrvT):
    """`server/discover` exists only at 2026-07-28, so a 2025 session rejects it even with a registered handler."""

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
    """Spec-mandated: `initialize` has no `CLIENT_REQUESTS` row; dispatch (not the classifier) rejects it."""
    born_ready = Connection.from_envelope(LATEST_MODERN_VERSION, None, None)
    async with connected_runner(server, initialized=False, connection=born_ready) as (client, runner):
        assert runner.connection.protocol_version == LATEST_MODERN_VERSION
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc.value.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_on_request_dispatches_custom_method_registered_via_add_request_handler(server: SrvT):
    """SDK-defined: methods outside `SPEC_CLIENT_METHODS` skip the version gate at any negotiated version."""

    async def echo(ctx: Ctx, params: RequestParams) -> dict[str, Any]:
        return {"echoed": True}

    server.add_request_handler("myorg/echo", RequestParams, echo)
    born_ready = Connection.from_envelope(LATEST_MODERN_VERSION, None, None)
    async with connected_runner(server, initialized=False, connection=born_ready) as (client, _):
        result = await client.send_raw_request("myorg/echo", None)
    assert result == {"echoed": True}


@pytest.mark.anyio
async def test_runner_middleware_short_circuit_on_a_wrong_version_spec_method_skips_the_sieve(server: SrvT):
    """The middleware owns the result shape; the sieve has no `(method, version)` row and must not raise."""

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
    """With grace 0 the deadline is expired on entry, so later unwind callbacks cancel at their first checkpoint."""
    monkeypatch.setattr(mcp.server.runner, "_EXIT_STACK_CLOSE_TIMEOUT", 0)
    ran: list[str] = []
    release = anyio.Event()

    async def _abandoned() -> None:
        # LIFO unwind runs this after the blocker, when the deadline has already
        # fired: the checkpoint raises, so the raise below is unreachable.
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
    """Uses the production grace: the deadline never delays a fast unwind, it only bounds a hung one."""
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


@pytest.mark.anyio
async def test_aclose_shielded_runs_callbacks_under_outer_cancellation():
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


@dataclass
class _StubDispatchContext:
    """Structurally satisfies the `DispatchContext` protocol for `serve_one` tests; no real back-channel."""

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
    """SDK-defined: a kernel-produced error propagates as `MCPError` and the exit stack still closes."""
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
    """The version gate reads `connection.protocol_version`; `logging/setLevel` is absent at modern versions."""
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
