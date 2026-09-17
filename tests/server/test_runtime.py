"""Public custom-transport hosting behavior, without a network broker."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

import anyio
import anyio.abc
import anyio.lowlevel
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ListToolsResult,
    PaginatedRequestParams,
    RequestId,
    TextContent,
    Tool,
)

from mcp import Client, MCPError
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.request_state import RequestStateSecurity
from mcp.server.runtime import ServerRuntime
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import Dispatcher, OnNotify, OnNotifyIntercept, OnRequest
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.transport import (
    DispatcherTransport,
    MessageMetadata,
    SessionMessage,
    TransportContext,
    TransportContextBuilder,
    TransportStreams,
)

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def connect(
    host: ServerRuntime[Any], *, transport_builder: TransportContextBuilder | None = None
) -> AsyncIterator[TransportStreams]:
    async with create_client_server_memory_streams() as (client_streams, server_streams):

        @asynccontextmanager
        async def transport() -> AsyncIterator[TransportStreams]:
            async with server_streams[0], server_streams[1]:
                yield server_streams

        await host.connect(transport(), transport_builder=transport_builder)
        yield client_streams


@pytest.mark.parametrize("highlevel", [False, True])
@pytest.mark.parametrize("modes", [("legacy", "legacy"), ("legacy", "2026-07-28"), ("2026-07-28", "2026-07-28")])
async def test_runtime_shares_lifespan_and_isolates_clients(highlevel: bool, modes: tuple[str, str]) -> None:
    """SDK hosting runs one lifespan while peers independently negotiate and dispatch overlapping requests."""
    lifecycle: list[str] = []
    entered = {"alice": anyio.Event(), "bob": anyio.Event()}
    request_ids: dict[str, RequestId | None] = {}

    @asynccontextmanager
    async def lifespan(server: Server[str] | MCPServer[str]) -> AsyncIterator[str]:
        lifecycle.append("startup")
        try:
            yield "shared-state"
        finally:
            lifecycle.append("shutdown")

    async def inspect(name: str, request_id: RequestId | None) -> str:
        request_ids[name] = request_id
        entered[name].set()
        await entered["bob" if name == "alice" else "alice"].wait()
        return name

    if highlevel:
        app = MCPServer("peers", lifespan=lifespan)

        @app.tool()
        async def echo(name: str, ctx: Context[str]) -> str:
            assert ctx.request_context.lifespan_context == "shared-state"
            return await inspect(name, ctx.request_context.request_id)

    else:

        async def echo_lowlevel(ctx: ServerRequestContext[str], params: CallToolRequestParams) -> CallToolResult:
            assert params.name == "echo"
            assert ctx.lifespan_context == "shared-state"
            assert params.arguments is not None
            name = params.arguments["name"]
            assert isinstance(name, str)
            return CallToolResult(content=[TextContent(text=await inspect(name, ctx.request_id))])

        async def list_tools(ctx: ServerRequestContext[str], params: PaginatedRequestParams | None) -> ListToolsResult:
            return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])

        app = Server("peers", lifespan=lifespan, on_call_tool=echo_lowlevel, on_list_tools=list_tools)

    results: dict[str, str] = {}

    async def call(client: Client, name: str) -> None:
        result = await client.call_tool("echo", {"name": name})
        content = result.content[0]
        assert isinstance(content, TextContent)
        results[name] = content.text

    with anyio.fail_after(5):
        async with app.serve() as host:
            async with Client(connect(host), mode=modes[0]) as alice:
                async with Client(connect(host), mode=modes[1]) as bob:
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(call, alice, "alice")
                        tg.start_soon(call, bob, "bob")
                if modes[0] == modes[1]:
                    assert request_ids["alice"] == request_ids["bob"]
                await call(alice, "alice")
            assert lifecycle == ["startup"]
        assert lifecycle == ["startup", "shutdown"]
    assert results == {"alice": "alice", "bob": "bob"}


@pytest.mark.parametrize("mode", ["legacy", "auto", "2026-07-28"])
async def test_host_exposes_adapter_metadata_in_highlevel_handlers(
    mode: Literal["legacy", "auto", "2026-07-28"],
) -> None:
    """Adapter context survives hosting; the modern protocol's back-channel denial remains authoritative."""

    @dataclass(kw_only=True, frozen=True)
    class BrokerContext(TransportContext):
        peer: str

    metadata = BrokerContext(kind="broker", can_send_request=True, peer="alice")

    def context_builder(message_metadata: MessageMetadata) -> BrokerContext:
        return metadata

    app = MCPServer("metadata")

    @app.tool()
    async def inspect_context(ctx: Context) -> dict[str, str | bool]:
        assert isinstance(ctx.transport, BrokerContext)
        return {"peer": ctx.transport.peer, "can_send_request": ctx.transport.can_send_request}

    with anyio.fail_after(5):
        async with app.serve() as host, Client(connect(host, transport_builder=context_builder), mode=mode) as client:
            result = await client.call_tool("inspect_context")
            assert result.structured_content == {"peer": metadata.peer, "can_send_request": mode == "legacy"}
    assert metadata.can_send_request is True


async def test_host_releases_transport_before_application_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host exit cancels a connected peer and lets its adapter clean up before the application does."""
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(server: Server[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await anyio.lowlevel.checkpoint()
            events.append("lifespan")

    request_send, request_receive = anyio.create_memory_object_stream[SessionMessage | Exception]()
    response_send, response_receive = anyio.create_memory_object_stream[SessionMessage]()
    async with request_send, request_receive, response_send, response_receive:
        server_streams = request_receive, response_send
        read_close, write_close = request_receive.aclose, response_send.aclose

        async def close_read() -> None:
            await anyio.lowlevel.checkpoint()
            events.append("read")
            await read_close()

        async def close_write() -> None:
            await anyio.lowlevel.checkpoint()
            events.append("write")
            await write_close()

        monkeypatch.setattr(server_streams[0], "aclose", close_read)
        monkeypatch.setattr(server_streams[1], "aclose", close_write)

        @asynccontextmanager
        async def transport() -> AsyncIterator[TransportStreams]:
            try:
                yield server_streams
            finally:
                await anyio.lowlevel.checkpoint()
                events.append("transport")

        with anyio.fail_after(5):
            async with Server("shutdown", lifespan=lifespan).serve() as host:
                await host.connect(transport())
        assert events == ["read", "write", "transport", "lifespan"]
        with pytest.raises(anyio.EndOfStream):
            await response_receive.receive()


async def test_host_survives_an_adapter_failure_after_opening(caplog: pytest.LogCaptureFixture) -> None:
    """An arbitrary adapter failure after readiness is isolated to its peer and logged with a traceback."""
    crash = anyio.Event()
    stopped = anyio.Event()

    async def fail() -> None:
        await crash.wait()
        raise OSError("broker disconnected")

    with anyio.fail_after(5):
        async with Server("isolation").serve() as host:
            async with create_client_server_memory_streams() as (client_streams, server_streams):

                @asynccontextmanager
                async def transport() -> AsyncIterator[TransportStreams]:
                    try:
                        async with anyio.create_task_group() as tg:
                            tg.start_soon(fail)
                            yield server_streams
                    finally:
                        stopped.set()

                await host.connect(transport())
                crash.set()
                await stopped.wait()
                async with Client(connect(host)) as healthy:
                    await healthy.session.discover()
                with pytest.raises(anyio.EndOfStream):
                    await client_streams[0].receive()
            assert stopped.is_set()
    errors = [record for record in caplog.records if record.name == "mcp.server.runtime"]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


async def test_host_propagates_opening_failure_without_poisoning_other_connections() -> None:
    """The caller of connect receives the original opening failure and can continue using the host."""
    failure = OSError("broker unavailable")

    @asynccontextmanager
    async def unavailable() -> AsyncIterator[TransportStreams]:
        raise failure
        yield

    with anyio.fail_after(5):
        async with Server("startup").serve() as host:
            with pytest.raises(OSError) as exc:
                await host.connect(unavailable())
            async with Client(connect(host)) as client:
                await client.session.discover()
            assert exc.value is failure


async def test_host_admission_waits_for_a_connection_slot() -> None:
    """The host opens no more than its configured number of logical peers, then admits a waiting peer on EOF."""
    opened = anyio.Event()

    with anyio.fail_after(5):
        async with Server("capacity").serve(max_connections=1) as host:
            async with (
                create_client_server_memory_streams() as (first_client, first_server),
                create_client_server_memory_streams() as (second_client, second_server),
                anyio.create_task_group() as tg,
            ):

                @asynccontextmanager
                async def first() -> AsyncIterator[TransportStreams]:
                    yield first_server

                @asynccontextmanager
                async def second() -> AsyncIterator[TransportStreams]:
                    opened.set()
                    yield second_server

                await host.connect(first())
                tg.start_soon(host.connect, second())
                await anyio.wait_all_tasks_blocked()
                assert not opened.is_set()
                await first_client[1].aclose()
                await opened.wait()
                await second_client[1].aclose()
            assert opened.is_set()


async def test_closed_host_rejects_connections_without_entering_the_transport() -> None:
    """Holding a host after its context exits does not allow new peers to outlive application lifespan."""

    @asynccontextmanager
    async def transport() -> AsyncIterator[TransportStreams]:
        raise NotImplementedError
        yield

    with anyio.fail_after(5):
        async with Server("closed").serve() as host:
            pass
        with pytest.raises(RuntimeError) as exc:
            await host.connect(transport())
        assert str(exc.value) == snapshot("Server runtime is closed")


@pytest.mark.parametrize("limit", [0, -1])
async def test_host_rejects_nonpositive_capacity_before_starting_lifespan(limit: int) -> None:
    """Invalid admission limits fail before the server acquires application resources."""

    @asynccontextmanager
    async def lifespan(server: Server[None]) -> AsyncIterator[None]:
        raise NotImplementedError
        yield None

    with pytest.raises(ValueError) as exc:
        async with Server("invalid", lifespan=lifespan).serve(max_connections=limit):
            raise NotImplementedError
    assert str(exc.value) == snapshot("max_connections must be positive")


async def test_host_shields_transport_and_lifespan_cleanup_from_parent_cancellation() -> None:
    """Cancelling the host owner still lets both cleanup layers perform asynchronous resource release."""
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(server: Server[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await anyio.lowlevel.checkpoint()
            events.append("lifespan")

    with anyio.fail_after(5):
        async with create_client_server_memory_streams() as (_, server_streams):

            @asynccontextmanager
            async def transport() -> AsyncIterator[TransportStreams]:
                try:
                    yield server_streams
                finally:
                    await anyio.lowlevel.checkpoint()
                    events.append("transport")

            with anyio.CancelScope() as scope:
                async with Server("cancel", lifespan=lifespan).serve() as host:
                    await host.connect(transport())
                    scope.cancel()
                    await anyio.sleep_forever()
            assert scope.cancelled_caught
    assert events == ["transport", "lifespan"]


@pytest.mark.parametrize("stall", ["transport", "lifespan"])
async def test_host_abandons_unresponsive_cleanup(stall: str, caplog: pytest.LogCaptureFixture) -> None:
    """SDK cleanup deadlines interrupt a stuck adapter or lifespan without parking shutdown forever."""
    interrupted = anyio.Event()

    async def cleanup(layer: str) -> None:
        if layer == stall:
            try:
                await anyio.sleep_forever()
            finally:
                interrupted.set()

    @asynccontextmanager
    async def lifespan(server: Server[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await cleanup("lifespan")

    # The behavior under test includes the documented five-second cleanup grace.
    with anyio.fail_after(10):
        async with create_client_server_memory_streams() as (_, server_streams):

            @asynccontextmanager
            async def transport() -> AsyncIterator[TransportStreams]:
                try:
                    yield server_streams
                finally:
                    await cleanup("transport")

            async with Server("stalled", lifespan=lifespan).serve() as host:
                await host.connect(transport())
        assert interrupted.is_set()
    records = [record for record in caplog.records if record.name == "mcp.server.runtime"]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"


async def test_runtime_bounds_transport_cleanup_after_normal_peer_eof(caplog: pytest.LogCaptureFixture) -> None:
    """A peer closing its stream finishes dispatch before the adapter's bounded cleanup begins."""
    interrupted = anyio.Event()
    # Normal EOF, followed by the documented five-second cleanup grace.
    with anyio.fail_after(10):
        async with create_client_server_memory_streams() as (client_streams, server_streams):

            @asynccontextmanager
            async def connection() -> AsyncIterator[TransportStreams]:
                try:
                    yield server_streams
                finally:
                    try:
                        await anyio.sleep_forever()
                    finally:
                        interrupted.set()

            async with Server("eof").serve() as runtime:
                await runtime.connect(connection())
                await client_streams[1].aclose()
                await interrupted.wait()
        assert interrupted.is_set()
    warnings = [record for record in caplog.records if record.name == "mcp.server.runtime"]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"


async def test_runtime_preserves_body_failure_when_lifespan_cleanup_times_out() -> None:
    """The cleanup deadline must not turn a failed listener into a successful context-manager exit."""
    failure = RuntimeError("listener failed")

    @asynccontextmanager
    async def lifespan(server: Server[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await anyio.sleep_forever()

    # This failure path includes the documented five-second cleanup grace.
    with anyio.fail_after(10), pytest.RaisesGroup(RuntimeError) as exc:
        async with Server("failed-listener", lifespan=lifespan).serve():
            raise failure
    assert exc.value.exceptions == (failure,)


@pytest.mark.parametrize("option", ["session_id", "transport_builder"])
async def test_native_runtime_rejects_stream_only_options_before_opening(option: str) -> None:
    """Native dispatchers supply their contexts and do not acquire legacy sessions from stream-hosting options."""

    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        raise NotImplementedError
        yield

    def builder(metadata: MessageMetadata) -> TransportContext:
        raise NotImplementedError

    with anyio.fail_after(5):
        async with Server("native").serve() as runtime:
            with pytest.raises(ValueError) as exc:
                await runtime.connect(
                    DispatcherTransport(connection()),
                    session_id="session" if option == "session_id" else None,
                    transport_builder=builder if option == "transport_builder" else None,
                )
            assert str(exc.value) == snapshot(
                "Dispatcher transports supply their own context and do not use handshake-era sessions"
            )


async def test_runtime_waits_for_native_dispatcher_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    """A native adapter is not connected until its receive loop has installed the MCP callbacks."""
    _, dispatcher = create_direct_dispatcher_pair()
    entered = anyio.Event()
    release = anyio.Event()
    connected = anyio.Event()
    run = dispatcher.run

    async def delayed_run(
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        entered.set()
        await release.wait()
        await run(on_request, on_notify, on_notify_intercept, task_status=task_status)

    monkeypatch.setattr(dispatcher, "run", delayed_run)

    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        yield dispatcher

    with anyio.fail_after(5):
        async with Server("readiness").serve() as runtime:

            async def connect_native() -> None:
                await runtime.connect(DispatcherTransport(connection()))
                connected.set()

            async with anyio.create_task_group() as tg:
                tg.start_soon(connect_native)
                await entered.wait()
                await anyio.wait_all_tasks_blocked()
                assert not connected.is_set()
                release.set()
                await connected.wait()
            assert connected.is_set()


async def test_runtime_propagates_native_dispatcher_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A native receive-loop startup failure reaches connect's caller rather than being logged after false readiness."""
    _, dispatcher = create_direct_dispatcher_pair()
    failure = RuntimeError("could not install RPC handlers")

    async def failing_run(
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        raise failure

    monkeypatch.setattr(dispatcher, "run", failing_run)

    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        yield dispatcher

    with anyio.fail_after(5):
        async with Server("startup").serve() as runtime:
            with pytest.raises(RuntimeError) as exc:
                await runtime.connect(DispatcherTransport(connection()))
            assert exc.value is failure


async def test_runtime_preserves_startup_failure_when_transport_cleanup_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck adapter cleanup must not replace its receive-loop startup failure with a false-readiness error."""
    _, dispatcher = create_direct_dispatcher_pair()
    failure = RuntimeError("native dispatcher failed to start")

    async def failing_run(
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        raise failure

    monkeypatch.setattr(dispatcher, "run", failing_run)

    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        try:
            yield dispatcher
        finally:
            await anyio.sleep_forever()

    # The failure includes the documented five-second adapter cleanup grace.
    with anyio.fail_after(10):
        async with Server("startup").serve() as runtime:
            with pytest.raises(RuntimeError) as exc:
                await runtime.connect(DispatcherTransport(connection()))
            assert exc.value is failure


async def test_runtime_keeps_request_state_bound_to_verified_peer_metadata() -> None:
    """The existing principal hook binds sealed state to adapter metadata, not caller-supplied claims.

    Both peers mint state concurrently, a cross-peer replay fails, and the original peer can still complete its request.
    """

    @dataclass(kw_only=True, frozen=True)
    class VerifiedPeer(TransportContext):
        principal: str

    def context_builder(metadata: MessageMetadata, *, principal: str) -> VerifiedPeer:
        return VerifiedPeer(kind="broker", can_send_request=True, principal=principal)

    def bind_principal(ctx: ServerRequestContext) -> str:
        if not isinstance(ctx.transport, VerifiedPeer):
            raise ValueError("Verified transport identity is required")
        return ctx.transport.principal

    server = MCPServer(
        "principals",
        request_state_security=RequestStateSecurity(
            keys=[b"test-key-for-principal-binding-32"], bind_principal=bind_principal
        ),
    )
    entered = {"alice": anyio.Event(), "bob": anyio.Event()}

    @server.tool()
    async def confirm(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is not None:
            assert ctx.request_state is not None
            return ctx.request_state
        assert isinstance(ctx.transport, VerifiedPeer)
        principal = ctx.transport.principal
        entered[principal].set()
        await entered["bob" if principal == "alice" else "alice"].wait()
        return InputRequiredResult(
            input_requests={
                "confirm": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Confirm?", requested_schema={"type": "object", "properties": {}}
                    )
                )
            },
            request_state=principal,
        )

    states: dict[str, str] = {}

    async def mint(client: Client, principal: str) -> None:
        result = await client.session.call_tool("confirm", allow_input_required=True)
        assert isinstance(result, InputRequiredResult)
        assert result.request_state is not None
        states[principal] = result.request_state

    with anyio.fail_after(5):
        async with server.serve() as runtime:
            async with (
                Client(connect(runtime, transport_builder=partial(context_builder, principal="alice"))) as alice,
                Client(connect(runtime, transport_builder=partial(context_builder, principal="bob"))) as bob,
            ):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(mint, alice, "alice")
                    tg.start_soon(mint, bob, "bob")
                with pytest.raises(MCPError) as exc:
                    await bob.session.call_tool(
                        "confirm",
                        input_responses={"confirm": ElicitResult(action="accept")},
                        request_state=states["alice"],
                        meta={"principal": "alice"},
                    )
                assert exc.value.code == INVALID_PARAMS
                assert exc.value.message == snapshot("Invalid or expired requestState")
                async with Client(connect(runtime)) as anonymous:
                    with pytest.raises(MCPError) as missing_identity:
                        await anonymous.session.call_tool(
                            "confirm",
                            input_responses={"confirm": ElicitResult(action="accept")},
                            request_state=states["alice"],
                        )
                    assert missing_identity.value.code == INVALID_PARAMS
                result = await alice.call_tool(
                    "confirm",
                    input_responses={"confirm": ElicitResult(action="accept")},
                    request_state=states["alice"],
                    meta={"principal": "bob"},
                )
            assert result.structured_content == {"result": "alice"}
