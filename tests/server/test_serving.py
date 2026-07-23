"""Tests for `serve_stream`, the era-deciding stream driver.

Each test speaks raw JSON-RPC frames to a `serve_stream` server through an
in-memory `JSONRPCDispatcher` client, so the wire behaviour under test is the
opening exchange: which era the connection opens in, what `server/discover`
does (answered, never opening), and how each posture answers traffic from the
other era. The ordering suite (`test_stdio_ordering.py`) covers pipelined
ordering on both anyio backends; these are the seam-level companions.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

import anyio
import anyio.abc
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    SERVER_INFO_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    CallToolRequestParams,
    CallToolResult,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolListChangedNotification,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS

from mcp.server.connection import NotifyOnlyOutbound
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.serving import Posture, _opening_intent, serve_listener, serve_stream
from mcp.server.stdio import newline_json_transport
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ToolsListChanged
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import SessionMessage
from mcp.shared.transport_context import TransportContext

from ..shared.test_dispatcher import Recorder, echo_handlers

pytestmark = pytest.mark.anyio

Ctx = ServerRequestContext[dict[str, Any], Any]


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """Run every test in this module on both anyio backends: the driver's ordering claims
    are owed to the dispatcher's sequential read loop, not to a task scheduler, and trio's
    scheduler is the check on that."""
    return request.param


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


SrvT = Server[dict[str, Any]]

_TOOL = Tool(name="t", input_schema={"type": "object"})


def _envelope(version: str = LATEST_MODERN_VERSION, *, with_client_info: bool = True) -> dict[str, Any]:
    meta: dict[str, Any] = {PROTOCOL_VERSION_META_KEY: version, CLIENT_CAPABILITIES_META_KEY: {}}
    if with_client_info:
        meta[CLIENT_INFO_META_KEY] = {"name": "test-client", "version": "1.0"}
    return meta


def _modern_params(version: str = LATEST_MODERN_VERSION, **params: Any) -> dict[str, Any]:
    return {**params, "_meta": _envelope(version)}


def _initialize_params() -> dict[str, Any]:
    return InitializeRequestParams(
        protocol_version=LATEST_HANDSHAKE_VERSION,
        capabilities=ClientCapabilities(),
        client_info=Implementation(name="test-client", version="1.0"),
    ).model_dump(by_alias=True, exclude_none=True)


def _server(*, posture: Posture = Posture.DUAL, **handlers: Any) -> SrvT:
    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[_TOOL])

    return Server(name="serve-stream-test", version="0.0.1", posture=posture, on_list_tools=list_tools, **handlers)


@asynccontextmanager
async def _raw_client(server: SrvT) -> AsyncIterator[tuple[JSONRPCDispatcher[TransportContext], Recorder]]:
    """Yield `(client, recorder)` speaking raw frames to a `serve_stream` server.

    The driver owns its dispatcher, connection, and lifespan, so the client here
    performs no handshake: each test drives the opening exchange itself.
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
        tg.start_soon(serve_stream, server, c2s_recv, s2c_send)
        try:
            with anyio.fail_after(5):
                yield client, recorder
        except BaseException as e:
            body_exc = e
        tg.cancel_scope.cancel()
    if body_exc is not None:
        raise body_exc


async def test_raw_client_harness_relays_a_failing_body_exception_unwrapped() -> None:
    """The `_raw_client` harness's own contract, pinned so its coverage stays whole:
    a failure raised inside the connection block surfaces as itself rather than as
    the task group's exception group, so a red test always reads as the assertion."""

    class _BodyFailed(Exception):
        pass

    with pytest.raises(_BodyFailed):
        async with _raw_client(_server()):
            raise _BodyFailed


# --- the opening decision ---------------------------------------------------


def test_opening_intent_is_read_off_the_opening_request_alone():
    """The one place an undecided connection's request intent is read. Posture is
    not an input here: it was consumed as the connection's starting era, so a
    single-era connection never asks this question."""
    envelope = {"_meta": _envelope()}
    assert _opening_intent("server/discover", envelope) == "probe"
    assert _opening_intent("initialize", envelope) == "legacy"  # legacy-distinctive even if stamped
    assert _opening_intent("tools/list", envelope) == "modern"
    assert _opening_intent("tools/list", {"_meta": {"progressToken": 1}}) == "legacy"  # not envelope evidence
    assert _opening_intent("tools/list", None) == "legacy"  # bare pre-handshake traffic
    assert _opening_intent("server/discover", None) == "legacy"  # an envelope-less discover is no probe


# --- dual-era posture --------------------------------------------------------


async def test_modern_request_opens_the_modern_era_and_refuses_the_handshake():
    """The first modern-envelope request pins the modern era; a later `initialize`
    is answered with the version error naming the modern versions."""
    async with _raw_client(_server()) as (client, _):
        result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"][0]["name"] == "t"
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert exc.value.error.data["supported"] == list(MODERN_PROTOCOL_VERSIONS)
    assert exc.value.error.data["requested"] == LATEST_HANDSHAKE_VERSION


async def test_initialize_opens_the_legacy_era_and_serves_the_handshake():
    async with _raw_client(_server()) as (client, _):
        init = await client.send_raw_request("initialize", _initialize_params())
        assert init["protocolVersion"] == LATEST_HANDSHAKE_VERSION
        await client.notify("notifications/initialized", None)
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"


async def test_legacy_era_refuses_a_modern_envelope_rather_than_serving_it():
    """A handshake connection speaks envelope-less traffic: an envelope-stamped
    request on it means the client is mixing eras, so the legacy era refuses it
    (-32600) instead of processing an era-ambiguous method under legacy
    semantics - a second, conflicting era claim on a committed connection is a
    client error, and the refusal is the deterministic answer."""
    async with _raw_client(_server()) as (client, _):
        await client.send_raw_request("initialize", _initialize_params())
        await client.notify("notifications/initialized", None)
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", _modern_params())
        # ...and the connection is still the same legacy connection afterwards.
        result = await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == INVALID_REQUEST
    assert result["tools"][0]["name"] == "t"


async def test_discover_probe_is_answered_without_pinning_the_era():
    """`server/discover` answers with modern semantics but leaves the connection
    undecided, so the fallback `initialize` that follows is still served (the
    stdio backward-compatibility probe flow)."""
    async with _raw_client(_server()) as (client, _):
        discover = await client.send_raw_request("server/discover", _modern_params())
        assert discover["supportedVersions"] == list(MODERN_PROTOCOL_VERSIONS)
        init = await client.send_raw_request("initialize", _initialize_params())
        assert init["protocolVersion"] == LATEST_HANDSHAKE_VERSION


async def test_slow_modern_request_pins_the_era_at_arrival_not_completion():
    """The straddle defect: a modern request that has not returned yet has still
    pinned the modern era, so a legacy handshake arriving meanwhile is refused."""
    tool_started = anyio.Event()
    release_tool = anyio.Event()

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        tool_started.set()
        await release_tool.wait()
        return CallToolResult(content=[TextContent(text="done")])

    error_code: int | None = None
    async with _raw_client(_server(on_call_tool=call_tool)) as (client, _):
        async with anyio.create_task_group() as tg:
            tg.start_soon(client.send_raw_request, "tools/call", _modern_params(name="slow"))
            await tool_started.wait()
            with pytest.raises(MCPError) as exc:
                await client.send_raw_request("initialize", _initialize_params())
            error_code = exc.value.error.code
            release_tool.set()
    assert error_code == UNSUPPORTED_PROTOCOL_VERSION


async def test_bare_initialized_notification_opens_the_legacy_era():
    """`notifications/initialized` is handshake vocabulary: a handshake completed
    without the `initialize` request. It is the one notification that opens an
    era (the legacy one), so the requests that follow are past the initialize
    gate."""
    async with _raw_client(_server()) as (client, _):
        await client.notify("notifications/initialized", None)
        result = await client.send_raw_request("tools/list", None)
    assert result["tools"][0]["name"] == "t"


async def test_bare_initialized_notification_is_admitted_before_its_context_is_built():
    """The handshake notification that opens the legacy era decides the era in
    receive order, before its own transport context is built: a handler that
    observes it already sees a legacy connection, whose channel offers the
    back-channel a duplex stream has (an undecided or modern connection would
    refuse server-initiated requests)."""
    seen: list[bool] = []
    observed = anyio.Event()

    async def on_initialized(ctx: Ctx, params: NotificationParams) -> None:
        seen.append(ctx.session.can_send_request)
        observed.set()

    server = _server()
    server.add_notification_handler("notifications/initialized", NotificationParams, on_initialized)
    async with _raw_client(server) as (client, _):
        await client.notify("notifications/initialized", None)
        with anyio.fail_after(5):
            await observed.wait()
    assert seen == [True], f"the initialized handler saw a not-yet-decided connection: {seen}"


async def test_stray_notification_opens_nothing_and_is_ignored():
    """Any other leading notification decides nothing: it is ignored, the
    connection stays undecided, and the modern request that follows still opens
    the modern era (a later handshake is refused with the version error)."""
    async with _raw_client(_server()) as (client, _):
        await client.notify("notifications/roots/list_changed", None)
        result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"][0]["name"] == "t"
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION


async def test_modern_client_notification_during_in_flight_work_is_delivered():
    """Once the modern era is pinned, an envelope-less client notification routes
    to the modern kernel and reaches its handler (it is no longer dropped as
    'received before initialization')."""
    seen = anyio.Event()

    async def on_ping_note(ctx: Ctx, params: NotificationParams) -> None:
        seen.set()

    server = _server()
    server.add_notification_handler("notifications/x/ping-note", NotificationParams, on_ping_note)
    async with _raw_client(server) as (client, _):
        await client.send_raw_request("tools/list", _modern_params())
        await client.notify("notifications/x/ping-note", None)
        await seen.wait()


async def test_pair_only_envelope_routes_to_the_modern_kernel():
    """The spec-required envelope pair (no clientInfo) is a modern request: it
    routes to the modern kernel rather than the legacy init-gate. A custom
    method (no per-version params surface) shows the routing directly, and
    its modern result carries the required `resultType` discriminator and the
    serverInfo `_meta` stamp (spec 2026-07-28, #3002)."""

    async def echo(ctx: Ctx, params: NotificationParams) -> dict[str, Any]:
        return {"protocolVersion": ctx.protocol_version}

    server = _server()
    server.add_request_handler("x/echo", NotificationParams, echo)
    params: dict[str, Any] = {"_meta": _envelope(with_client_info=False)}
    async with _raw_client(server) as (client, _):
        result = await client.send_raw_request("x/echo", params)
    assert result == {
        "protocolVersion": LATEST_MODERN_VERSION,
        "resultType": "complete",
        "_meta": {SERVER_INFO_META_KEY: {"name": "serve-stream-test", "version": "0.0.1"}},
    }


async def test_bare_request_on_a_modern_connection_is_a_malformed_modern_request():
    """After the modern era is pinned, an envelope-less request is answered in
    modern vocabulary: the envelope pair is required, so it is INVALID_PARAMS."""
    async with _raw_client(_server()) as (client, _):
        await client.send_raw_request("tools/list", _modern_params())
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == INVALID_PARAMS


async def test_pair_only_spec_request_is_served_and_records_capabilities_without_client_params():
    """Spec-mandated (spec PR #3002): the required envelope pair (protocol version
    + client capabilities) without the optional clientInfo is a complete modern
    spec request - it is served (not -32602), pins the modern era, and records
    the declared capabilities while client params stay unset."""
    seen: list[ServerRequestContext[Any, Any]] = []

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        seen.append(ctx)
        return CallToolResult(content=[TextContent(type="text", text=params.name)])

    server = _server(on_call_tool=call_tool)
    params = {"name": "echo", "_meta": _envelope(with_client_info=False)}
    async with _raw_client(server) as (client, _):
        result = await client.send_raw_request("tools/call", params)
        assert result["content"][0]["text"] == "echo"
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
    assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert seen[0].session.client_params is None
    assert seen[0].session.client_capabilities == ClientCapabilities()


async def test_version_without_capabilities_is_rejected_naming_the_missing_key():
    """A `_meta` declaring the protocol version but missing the required
    client-capabilities key is a malformed modern request: it is answered
    INVALID_PARAMS naming the missing key, in modern vocabulary. The opening
    request declared modern intent, so the connection is a modern one and the
    corrected pair is served without a handshake."""
    params: dict[str, Any] = {"_meta": {PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION}}
    async with _raw_client(_server()) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", params)
        result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"][0]["name"] == "t"
    assert exc.value.error.code == INVALID_PARAMS
    assert CLIENT_CAPABILITIES_META_KEY in exc.value.error.message


async def test_modern_era_refuses_server_initiated_requests_but_carries_notifications():
    """The modern protocol forbids server-initiated requests: the request-scoped
    channel refuses (via the transport context), while notifications still
    ride the duplex pipe."""

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        assert isinstance(ctx.session._connection.outbound, NotifyOnlyOutbound)  # pyright: ignore[reportPrivateUsage]
        assert ctx.session.can_send_request is False
        with pytest.raises(NoBackChannelError):
            await ctx.session.send_ping()
        await ctx.session.send_notification(ToolListChangedNotification(), related_request_id=ctx.request_id)
        return CallToolResult(content=[TextContent(text="ok")])

    async with _raw_client(_server(on_call_tool=call_tool)) as (client, recorder):
        await client.send_raw_request("tools/call", _modern_params(name="t"))
        await recorder.notified.wait()
    assert recorder.notifications[0][0] == "notifications/tools/list_changed"


async def test_modern_era_carries_standalone_notifications_over_the_duplex_pipe():
    """A server notification sent with no `related_request_id` rides the connection's
    standalone channel (`NotifyOnlyOutbound`): over a duplex stream it reaches the peer."""

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        await ctx.session.send_notification(ToolListChangedNotification())  # no related_request_id
        return CallToolResult(content=[TextContent(text="ok")])

    async with _raw_client(_server(on_call_tool=call_tool)) as (client, recorder):
        await client.send_raw_request("tools/call", _modern_params(name="t"))
        with anyio.fail_after(5):
            await recorder.notified.wait()
    assert recorder.notifications[0][0] == "notifications/tools/list_changed"


async def test_modern_era_passes_a_handler_mcp_error_through_with_its_own_code():
    """An `MCPError` a modern handler raises is not sanitized: it is the handler's
    deliberate wire error, so it reaches the client with its code and message intact."""

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        raise MCPError(code=INVALID_PARAMS, message="tool refused these arguments")

    async with _raw_client(_server(on_call_tool=call_tool)) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", _modern_params(name="t"))
    assert exc.value.error.code == INVALID_PARAMS
    assert exc.value.error.message == "tool refused these arguments"


async def test_serve_stream_with_raise_exceptions_reraises_a_modern_handler_exception():
    """`raise_exceptions=True` (an in-process testing aid) re-raises a modern handler's
    unmapped exception out of `serve_stream` after the peer has been answered."""

    class _Kaboom(Exception):
        pass

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        raise _Kaboom("surfaces out of the driver")

    server = _server(on_call_tool=call_tool)
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    c_req, c_notify = echo_handlers(Recorder())
    with pytest.raises(BaseException) as excinfo:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, c_req, c_notify)
            tg.start_soon(partial(serve_stream, server, c2s_recv, s2c_send, raise_exceptions=True))
            # The client is still answered (generically) before the exception escapes.
            with anyio.fail_after(5), pytest.raises(MCPError) as wire:
                await client.send_raw_request("tools/call", _modern_params(name="t"))
            assert wire.value.error.code == INTERNAL_ERROR
    assert excinfo.group_contains(_Kaboom)


async def test_modern_era_sanitizes_unmapped_handler_exceptions_to_internal_error():
    """An unmapped handler exception on the modern era is answered like the modern
    HTTP entry answers it: a generic INTERNAL_ERROR, so handler internals never
    reach the wire (unlike the legacy era's `code=0, str(e)`)."""

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        raise RuntimeError("db password is hunter2")

    async with _raw_client(_server(on_call_tool=call_tool)) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", _modern_params(name="t"))
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Internal server error"


async def test_modern_only_posture_refuses_a_handshake_with_no_parseable_version():
    """When `initialize` carries no parseable `protocolVersion`, the modern era's
    refusal still names the versions it serves (there is nothing to echo back)."""
    async with _raw_client(_server(posture=Posture.MODERN_ONLY)) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", {"capabilities": {}})
    assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert exc.value.error.data == {"supported": list(MODERN_PROTOCOL_VERSIONS)}


# --- single-era postures -----------------------------------------------------


async def test_modern_only_posture_refuses_the_handshake_naming_its_versions():
    """A modern-only server answers `initialize` with -32022 listing the modern
    versions (versioning.mdx: modern-only servers SHOULD name them), and serves
    modern requests."""
    async with _raw_client(_server(posture=Posture.MODERN_ONLY)) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("initialize", _initialize_params())
        assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
        assert exc.value.error.data["supported"] == list(MODERN_PROTOCOL_VERSIONS)
        result = await client.send_raw_request("tools/list", _modern_params())
    assert result["tools"][0]["name"] == "t"


async def test_legacy_only_posture_serves_the_handshake_and_answers_probes_in_legacy_vocabulary():
    """A legacy-only server is born a handshake connection: an enveloped probe is
    a client mixing eras and is refused (-32600), a bare probe is answered with
    the handshake era's own method-not-found - both trigger an auto client's
    fallback, since fallback is not keyed to one code - and the handshake works."""
    async with _raw_client(_server(posture=Posture.LEGACY_ONLY)) as (client, _):
        with pytest.raises(MCPError) as enveloped:
            await client.send_raw_request("server/discover", _modern_params())
        with pytest.raises(MCPError) as bare:
            await client.send_raw_request("server/discover", None)
        init = await client.send_raw_request("initialize", _initialize_params())
    assert enveloped.value.error.code == INVALID_REQUEST
    assert bare.value.error.code == METHOD_NOT_FOUND
    assert init["protocolVersion"] == LATEST_HANDSHAKE_VERSION


# --- subscriptions/listen over a stream --------------------------------------


async def test_stdin_eof_ends_open_listen_streams_gracefully_before_the_connection_closes() -> None:
    """The peer closing our input is the server's cue to wind down: an open
    `subscriptions/listen` stream is told to close inside the shielded drain, so
    its `SubscriptionsListenResult` reaches the (still-open) output before the
    write side closes - the drain waits for every request task to finish, and a
    task finishes only once its answer is written."""
    bus = InMemorySubscriptionBus()
    server = _server(on_subscriptions_listen=ListenHandler(bus))
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage](8)
    envelope = _envelope()
    listen = JSONRPCRequest(
        jsonrpc="2.0",
        id="sub-1",
        method="subscriptions/listen",
        params={"notifications": {"toolsListChanged": True}, "_meta": envelope},
    )
    frames: list[Any] = []
    async with c2s_send, s2c_recv, anyio.create_task_group() as tg:
        tg.start_soon(serve_stream, server, c2s_recv, s2c_send)
        await c2s_send.send(SessionMessage(listen))
        with anyio.fail_after(5):
            frames.append((await s2c_recv.receive()).message)  # the acknowledgment
        c2s_send.close()  # peer EOF with the stream open
        with anyio.fail_after(5):
            frames.extend([item.message async for item in s2c_recv])  # the drain, then close
    kinds: list[type] = [type(frame) for frame in frames]
    assert kinds == [JSONRPCNotification, JSONRPCResponse]
    result = frames[1]
    assert isinstance(result, JSONRPCResponse)
    assert result.id == "sub-1" and result.result["resultType"] == "complete"


async def test_stdin_eof_on_one_connection_ends_the_listen_streams_of_every_connection_sharing_the_server():
    """Pins the multi-connection caveat: the drain at read EOF tells the *server's*
    `ListenHandler` to close, and that handler is shared by every connection the
    `Server` serves, so connection A's input closing also ends connection B's open
    listen stream - B is handed its graceful `SubscriptionsListenResult` unprompted.
    SDK-defined, not spec-mandated: when subscription streams become per-connection
    (the bus-first `Server` follow-up), B's stream must stay open here and the
    marked expectation below flips.
    """
    bus = InMemorySubscriptionBus()
    server = _server(on_subscriptions_listen=ListenHandler(bus))
    listen_params = {"notifications": {"toolsListChanged": True}, "_meta": _envelope()}

    def listen_request(request_id: str) -> SessionMessage:
        return SessionMessage(
            JSONRPCRequest(jsonrpc="2.0", id=request_id, method="subscriptions/listen", params=listen_params)
        )

    a_in_send, a_in_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    a_out_send, a_out_recv = anyio.create_memory_object_stream[SessionMessage](8)
    b_in_send, b_in_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    b_out_send, b_out_recv = anyio.create_memory_object_stream[SessionMessage](8)
    a_frames: list[JSONRPCMessage] = []
    b_frames: list[JSONRPCMessage] = []
    async with (
        a_in_send,
        a_out_recv,
        b_in_send,
        b_out_recv,
        server.lifespan() as lifespan_state,  # one entered lifespan shared by both connections
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(partial(serve_stream, server, a_in_recv, a_out_send, lifespan_state=lifespan_state))
        tg.start_soon(partial(serve_stream, server, b_in_recv, b_out_send, lifespan_state=lifespan_state))
        await a_in_send.send(listen_request("sub-a"))
        await b_in_send.send(listen_request("sub-b"))
        with anyio.fail_after(5):  # both streams open: each connection's first frame is its ack
            a_frames.append((await a_out_recv.receive()).message)
            b_frames.append((await b_out_recv.receive()).message)
        a_in_send.close()  # connection A's peer EOF, with A's stream open
        with anyio.fail_after(5):
            a_frames.extend([item.message async for item in a_out_recv])  # A's graceful result, then close
        # TODAY (the documented caveat): A's drain closed the server-wide ListenHandler,
        # so B's stream ended with it and B receives its listen result without asking. When
        # streams are owned per connection, flip this: nothing arrives on B's output here
        # and B's stream keeps delivering events.
        with anyio.fail_after(5):
            b_frames.append((await b_out_recv.receive()).message)
        tg.cancel_scope.cancel()
    assert [type(frame) for frame in a_frames] == [JSONRPCNotification, JSONRPCResponse]
    assert [type(frame) for frame in b_frames] == [JSONRPCNotification, JSONRPCResponse]
    a_result, b_result = a_frames[1], b_frames[1]
    assert isinstance(a_result, JSONRPCResponse) and a_result.id == "sub-a"
    assert a_result.result["resultType"] == "complete"
    assert isinstance(b_result, JSONRPCResponse) and b_result.id == "sub-b"  # B never asked to close
    assert b_result.result["resultType"] == "complete"


async def test_listen_is_served_over_a_stream_ack_first_event_then_graceful_close():
    """A subscription is a request in flight: over a duplex stream the listen
    handler acks first, delivers a stamped event, and closes gracefully with the
    empty `subscriptions/listen` result when the server ends the stream through
    its `close_subscriptions()` verb."""
    bus = InMemorySubscriptionBus()
    server = _server(on_subscriptions_listen=ListenHandler(bus))
    results: list[dict[str, Any]] = []
    listen_id = "sub-1"
    async with _raw_client(server) as (client, recorder):

        async def open_listen() -> None:
            results.append(
                await client.send_raw_request(
                    "subscriptions/listen",
                    _modern_params(notifications={"toolsListChanged": True}),
                    {"request_id": listen_id},
                )
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(open_listen)
            await recorder.notified.wait()  # the acknowledgment
            await bus.publish(ToolsListChanged())
            # The stream flushes the event, then the graceful close ends it: the
            # response only arrives once the handler returns its result.
            recorder.notified = anyio.Event()
            await recorder.notified.wait()  # the delivered event
            server.close_subscriptions()  # server-initiated graceful close

    methods = [name for name, _ in recorder.notifications]
    assert methods == ["notifications/subscriptions/acknowledged", "notifications/tools/list_changed"]
    for _, params in recorder.notifications:
        assert params is not None
        assert params["_meta"]["io.modelcontextprotocol/subscriptionId"] == listen_id
    assert results[0]["resultType"] == "complete"
    assert results[0]["_meta"]["io.modelcontextprotocol/subscriptionId"] == listen_id


# --- serve_listener: the socket-shaped host --------------------------------------


@asynccontextmanager
async def _client_over_socket(
    stream: anyio.abc.ByteStream,
) -> AsyncIterator[tuple[JSONRPCDispatcher[TransportContext], Recorder]]:
    """Yield a raw JSON-RPC client speaking the stdio wire over one byte stream."""
    async with newline_json_transport(stream) as (read_stream, write_stream):
        client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_stream, write_stream)
        recorder = Recorder()
        c_req, c_notify = echo_handlers(recorder)
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, c_req, c_notify)
            try:
                yield client, recorder
            finally:
                tg.cancel_scope.cancel()


async def _serve_on_tcp(server: SrvT, task_group: anyio.abc.TaskGroup) -> tuple[int, Any]:
    """Start `serve_listener` on an ephemeral loopback port; return `(port, listener)`."""
    listener = await anyio.create_tcp_listener(local_host="127.0.0.1")
    port = listener.extra(anyio.abc.SocketAttribute.local_port)
    task_group.start_soon(serve_listener, server, listener)
    return port, listener


async def test_serve_listener_frames_and_serves_each_accepted_connection():
    """The socket host: a raw newline-JSON-RPC client over TCP gets its request served."""
    server = _server()
    async with anyio.create_task_group() as tg:
        port, _ = await _serve_on_tcp(server, tg)
        with anyio.fail_after(5):
            stream = await anyio.connect_tcp("127.0.0.1", port)
            async with stream, _client_over_socket(stream) as (client, _):
                result = await client.send_raw_request("tools/list", _modern_params())
        assert result["tools"] == [_TOOL.model_dump(by_alias=True, exclude_none=True)]
        tg.cancel_scope.cancel()


async def test_serve_listener_enters_the_lifespan_once_for_every_connection():
    """Connections never re-enter the lifespan: the listener shares one entered state."""
    entered: list[str] = []

    @asynccontextmanager
    async def lifespan(_: SrvT) -> AsyncIterator[dict[str, Any]]:
        entered.append("enter")
        try:
            yield {"db": "shared"}
        finally:
            entered.append("exit")

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(text=ctx.lifespan_context["db"])])

    server = Server(name="shared-lifespan", version="0.0.1", lifespan=lifespan, on_call_tool=call_tool)
    async with anyio.create_task_group() as tg:
        port, _ = await _serve_on_tcp(server, tg)
        with anyio.fail_after(5):
            for _ in range(2):
                stream = await anyio.connect_tcp("127.0.0.1", port)
                async with stream, _client_over_socket(stream) as (client, _):
                    result = await client.send_raw_request("tools/call", _modern_params(name="db", arguments={}))
                    assert result["content"] == [{"type": "text", "text": "shared"}]
        tg.cancel_scope.cancel()

    assert entered == ["enter", "exit"]


async def test_serve_listener_owns_the_listener_and_closes_it_when_cancelled():
    """The host runs until cancelled and takes the listener with it: nothing to close by hand."""
    listener = await anyio.create_tcp_listener(local_host="127.0.0.1")
    raw = listener.extra(anyio.abc.SocketAttribute.raw_socket)
    async with anyio.create_task_group() as tg:
        tg.start_soon(serve_listener, _server(), listener)
        with anyio.fail_after(5):  # a client can connect: the listener is being served
            connection = await anyio.connect_tcp("127.0.0.1", listener.extra(anyio.abc.SocketAttribute.local_port))
            await connection.aclose()
        assert raw.fileno() != -1
        tg.cancel_scope.cancel()
    assert raw.fileno() == -1  # closed by serve_listener on the way out
