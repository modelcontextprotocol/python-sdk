"""Behavioral tests for the Dispatcher Protocol.

The contract tests are parametrized over every `Dispatcher` implementation via
the `pair_factory` fixture (see `conftest.py`); they must pass for both
`DirectDispatcher` and `JSONRPCDispatcher`. Implementation-specific tests pass
a concrete factory directly.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import anyio
import pytest
from mcp_types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    REQUEST_TIMEOUT,
    ElicitRequestURLParams,
    ErrorData,
    Tool,
)

from mcp.shared._compat import resync_tracer
from mcp.shared.direct_dispatcher import DirectDispatcher, create_direct_dispatcher_pair
from mcp.shared.dispatcher import DispatchContext, Dispatcher, OnNotify, OnRequest, Outbound
from mcp.shared.exceptions import MCPError, NoBackChannelError, UrlElicitationRequiredError
from mcp.shared.transport_context import TransportContext

from .conftest import PairFactory, direct_pair


class Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Mapping[str, Any] | None]] = []
        self.notifications: list[tuple[str, Mapping[str, Any] | None]] = []
        self.contexts: list[DispatchContext[TransportContext]] = []
        self.notified = anyio.Event()


def echo_handlers(recorder: Recorder) -> tuple[OnRequest, OnNotify]:
    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        # Strip `_meta` so JSON-RPC and direct dispatch record identically:
        # the JSON-RPC outbound path always attaches `_meta` (otel injection).
        recorded = {k: v for k, v in (params or {}).items() if k != "_meta"} if params is not None else None
        recorder.requests.append((method, recorded))
        recorder.contexts.append(ctx)
        return {"echoed": method, "params": recorded or {}}

    async def on_notify(ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        recorder.notifications.append((method, params))
        recorder.notified.set()

    return on_request, on_notify


@asynccontextmanager
async def running_pair(
    factory: PairFactory,
    *,
    server_on_request: OnRequest | None = None,
    server_on_notify: OnNotify | None = None,
    client_on_request: OnRequest | None = None,
    client_on_notify: OnNotify | None = None,
    can_send_request: bool = True,
) -> AsyncIterator[tuple[Dispatcher[TransportContext], Dispatcher[TransportContext], Recorder, Recorder]]:
    """Yield `(client, server, client_recorder, server_recorder)` with both `run()` loops live."""
    client, server, close = factory(can_send_request=can_send_request)
    client_rec, server_rec = Recorder(), Recorder()
    c_req, c_notify = echo_handlers(client_rec)
    s_req, s_notify = echo_handlers(server_rec)
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, client_on_request or c_req, client_on_notify or c_notify)
            await tg.start(server.run, server_on_request or s_req, server_on_notify or s_notify)
            try:
                yield client, server, client_rec, server_rec
            finally:
                tg.cancel_scope.cancel()
    finally:
        await resync_tracer()
        close()


@pytest.mark.anyio
async def test_send_raw_request_returns_result_from_peer_on_request(pair_factory: PairFactory):
    async with running_pair(pair_factory) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            result = await client.send_raw_request("tools/list", {"cursor": "abc"})
    assert result == {"echoed": "tools/list", "params": {"cursor": "abc"}}
    assert srec.requests == [("tools/list", {"cursor": "abc"})]


@pytest.mark.anyio
async def test_send_raw_request_surfaces_handler_mcperror_code_and_message(pair_factory: PairFactory):
    """A handler-raised `MCPError`'s code and message surface to the caller on every
    dispatcher (SDK-defined). The caller gets an equal-valued re-raise, not the
    handler's exception object — see the subclass-flattening test below."""

    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        raise MCPError(code=INVALID_PARAMS, message="bad cursor")

    async with running_pair(pair_factory, server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", {})
    assert exc.value.error.code == INVALID_PARAMS
    assert exc.value.error.message == "bad cursor"


@pytest.mark.anyio
async def test_send_raw_request_flattens_handler_mcperror_subclass_to_plain_mcperror(pair_factory: PairFactory):
    """A handler-raised `MCPError` subclass surfaces to the caller as plain `MCPError`
    with equal `ErrorData` on every dispatcher (SDK-defined): subclass identity cannot
    cross the JSON-RPC wire, and `DirectDispatcher` matches so in-process callers see
    the same error surface. Callers needing the subclass rehydrate it from the error
    data (e.g. `UrlElicitationRequiredError.from_error`)."""
    raised: list[UrlElicitationRequiredError] = []

    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        error = UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    message="Authorization required",
                    url="https://example.com/authorize",
                    elicitation_id="auth-001",
                )
            ]
        )
        raised.append(error)
        raise error

    async with running_pair(pair_factory, server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {})
    # Flattened: exactly MCPError, the subclass type does not survive dispatch.
    assert type(exc.value) is MCPError
    # ...but the full ErrorData (code/message/data) of the raised subclass does.
    assert exc.value.error == raised[0].error


@pytest.mark.anyio
async def test_send_raw_request_maps_validation_error_to_invalid_params(pair_factory: PairFactory):
    """A pydantic `ValidationError` from the handler surfaces as the
    normalized INVALID_PARAMS shape on every dispatcher."""

    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        Tool.model_validate({"name": 123})  # raises ValidationError
        raise NotImplementedError

    async with running_pair(pair_factory, server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


@pytest.mark.anyio
async def test_send_raw_request_with_timeout_raises_mcperror_request_timeout(pair_factory: PairFactory):
    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await anyio.sleep_forever()
        raise NotImplementedError

    async with running_pair(pair_factory, server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("slow", None, {"timeout": 0})
    assert exc.value.error.code == REQUEST_TIMEOUT


@pytest.mark.anyio
async def test_notify_invokes_peer_on_notify(pair_factory: PairFactory):
    async with running_pair(pair_factory) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.notify("notifications/initialized", {"v": 1})
            await srec.notified.wait()
    assert srec.notifications == [("notifications/initialized", {"v": 1})]


@pytest.mark.anyio
async def test_ctx_send_raw_request_round_trips_to_calling_side(pair_factory: PairFactory):
    """A handler's ctx.send_raw_request reaches the side that made the inbound request."""

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        sample = await ctx.send_raw_request("sampling/createMessage", {"prompt": "hi"})
        return {"sampled": sample}

    async with running_pair(pair_factory, server_on_request=server_on_request) as (client, _server, crec, _srec):
        with anyio.fail_after(5):
            result = await client.send_raw_request("tools/call", None)
    assert crec.requests == [("sampling/createMessage", {"prompt": "hi"})]
    assert result == {"sampled": {"echoed": "sampling/createMessage", "params": {"prompt": "hi"}}}


@pytest.mark.anyio
async def test_ctx_send_raw_request_raises_nobackchannelerror_when_transport_disallows(pair_factory: PairFactory):
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        return await ctx.send_raw_request("sampling/createMessage", None)

    async with running_pair(pair_factory, server_on_request=server_on_request, can_send_request=False) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", None)
    assert exc.value.error.code == INVALID_REQUEST


@pytest.mark.anyio
async def test_ctx_notify_invokes_calling_side_on_notify(pair_factory: PairFactory):
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await ctx.notify("notifications/message", {"level": "info"})
        return {}

    async with running_pair(pair_factory, server_on_request=server_on_request) as (client, _server, crec, _srec):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None)
            await crec.notified.wait()
    assert crec.notifications == [("notifications/message", {"level": "info"})]


@pytest.mark.anyio
async def test_ctx_progress_invokes_caller_on_progress_callback(pair_factory: PairFactory):
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await ctx.progress(0.5, total=1.0, message="halfway")
        return {}

    received: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async with running_pair(pair_factory, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None, {"on_progress": on_progress})
    assert received == [(0.5, 1.0, "halfway")]


@pytest.mark.anyio
async def test_ctx_progress_is_noop_when_caller_supplied_no_callback(pair_factory: PairFactory):
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await ctx.progress(0.5)
        return {"ok": True}

    async with running_pair(pair_factory, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            result = await client.send_raw_request("tools/call", None)
    assert result == {"ok": True}


@pytest.mark.anyio
async def test_ctx_progress_and_notify_after_the_inbound_request_returns_are_dropped(
    pair_factory: PairFactory,
) -> None:
    """A dispatch context is closed once its inbound request finishes, so a captured context's
    `progress` and `notify` after the handler has returned deliver nothing.

    This is the `DispatchContext` contract (the `can_send_request` docstring in
    `mcp/shared/dispatcher.py` names the closed state). The in-handler 0.5 report is the
    positive control proving the progress channel works; the second round-trip after the
    late calls flushes anything they would have put in flight, so the negative is not racy.

    `received == [(0.5, ...)]` is the load-bearing arm of the proof on `DirectDispatcher`,
    which delivers progress straight to the caller's callback (no client-side late-drop
    exists there). The `notifications/message` absence is the load-bearing arm on
    `JSONRPCDispatcher`, whose receiving side tees every inbound notification to `on_notify`
    regardless of callback registration.
    """
    received: list[tuple[float, float | None, str | None]] = []
    contexts: list[DispatchContext[TransportContext]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        contexts.append(ctx)
        await ctx.progress(0.5, total=1.0, message="halfway")
        return {}

    async with running_pair(pair_factory, server_on_request=server_on_request) as (client, _server, crec, _srec):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None, {"on_progress": on_progress})
            late_ctx = contexts[0]
            await late_ctx.progress(1.0)
            await late_ctx.notify("notifications/message", {"level": "late"})
            await client.send_raw_request("tools/call", None)
    assert received == [(0.5, 1.0, "halfway")]
    assert ("notifications/message", {"level": "late"}) not in crec.notifications


@pytest.mark.anyio
async def test_ctx_send_raw_request_after_the_inbound_request_returns_raises_no_back_channel(
    pair_factory: PairFactory,
) -> None:
    """A dispatch context's back-channel closes with its inbound request: once the handler has
    returned, `can_send_request` is `False` and `send_raw_request` raises `NoBackChannelError`.

    This is the `DispatchContext` contract: `can_send_request` is `False` once the context has
    been closed, and `send_raw_request` raises exactly then. The in-handler `True` is the
    positive control -- the same context's back-channel was open while the request was in
    flight, and the dispatcher pair is still running, so the rejection is the per-request
    close, not a missing transport back-channel or a torn-down connection.
    """
    contexts: list[DispatchContext[TransportContext]] = []
    open_while_handling: list[bool] = []

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        contexts.append(ctx)
        open_while_handling.append(ctx.can_send_request)
        return {}

    async with running_pair(pair_factory, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None)
            late_ctx = contexts[0]
            assert open_while_handling == [True]
            assert late_ctx.can_send_request is False
            with pytest.raises(NoBackChannelError) as exc:
                await late_ctx.send_raw_request("ping", None)
            assert exc.value.code == INVALID_REQUEST


@pytest.mark.anyio
async def test_ctx_message_metadata_is_none_when_transport_attaches_nothing(pair_factory: PairFactory):
    """Plain requests carry no transport metadata, so handlers see `None`."""
    async with running_pair(pair_factory) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None)
    assert len(srec.contexts) == 1
    assert srec.contexts[0].message_metadata is None


@pytest.mark.anyio
async def test_ctx_request_id_exposes_inbound_id(pair_factory: PairFactory):
    """Every dispatcher assigns each inbound request a distinct int id; JSON-RPC carries
    the wire id through, DirectDispatcher synthesizes one (SDK-defined)."""
    async with running_pair(pair_factory) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None)
            await client.send_raw_request("tools/call", None)
    a, b = (ctx.request_id for ctx in srec.contexts)
    assert isinstance(a, int) and isinstance(b, int)
    assert a != b


@pytest.mark.anyio
async def test_direct_send_raw_request_wraps_non_mcperror_exception_as_internal_error_with_cause():
    """DirectDispatcher-specific: the original exception is chained via __cause__."""

    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        raise ValueError("oops")

    async with running_pair(direct_pair, server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", {})
        assert exc.value.error.code == INTERNAL_ERROR
        assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.anyio
async def test_direct_send_raw_request_issued_before_peer_run_blocks_until_peer_ready():
    client, server = create_direct_dispatcher_pair()
    s_req, s_notify = echo_handlers(Recorder())
    c_req, c_notify = echo_handlers(Recorder())

    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        # start_soon: the server side only becomes ready once the request below has parked.
        tg.start_soon(server.run, s_req, s_notify)
        with anyio.fail_after(5):
            result = await client.send_raw_request("ping", None)
        assert result == {"echoed": "ping", "params": {}}
        client.close()
        server.close()


@pytest.mark.anyio
async def test_direct_send_raw_request_before_run_raises_runtimeerror():
    """The not-running guard fires immediately - before any waiting on the peer - matching JSONRPCDispatcher."""
    client, _server = create_direct_dispatcher_pair()
    with anyio.fail_after(5), pytest.raises(RuntimeError) as exc:
        await client.send_raw_request("ping", None)
    assert str(exc.value) == "DirectDispatcher.send_raw_request called before run()"


@pytest.mark.anyio
async def test_direct_send_raw_request_to_never_run_peer_honors_timeout():
    """A configured timeout bounds the wait for a peer whose run() has not started."""
    client, _server = create_direct_dispatcher_pair()
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("ping", None, {"timeout": 0})
        assert exc.value.error.code == REQUEST_TIMEOUT
        client.close()


@pytest.mark.anyio
async def test_direct_request_parked_waiting_for_peer_run_is_woken_by_peer_close():
    """A request waiting on a never-run peer fails with CONNECTION_CLOSED when that peer closes."""
    client, server = create_direct_dispatcher_pair()
    c_req, c_notify = echo_handlers(Recorder())
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, c_req, c_notify)

            async def send() -> None:
                with pytest.raises(MCPError) as exc:
                    await client.send_raw_request("ping", None)
                assert exc.value.error.code == CONNECTION_CLOSED
                client.close()

            tg.start_soon(send)
            await anyio.wait_all_tasks_blocked()
            server.close()


@pytest.mark.anyio
async def test_direct_send_raw_request_after_local_close_raises_and_notify_is_dropped():
    """After this side has closed, send_raw_request raises CONNECTION_CLOSED and notify
    drops fire-and-forget, matching JSONRPCDispatcher (SDK-defined)."""
    async with running_pair(direct_pair) as (client, _server, _crec, srec):
        pass  # exiting cancels both run() loops, closing both sides
    with pytest.raises(MCPError) as exc:
        await client.send_raw_request("ping", None)
    assert exc.value.error.code == CONNECTION_CLOSED
    await client.notify("notifications/roots/list_changed", None)
    assert srec.requests == []
    assert srec.notifications == []


@pytest.mark.anyio
async def test_direct_inbound_after_peer_close_refuses_requests_and_drops_notifications():
    """Dispatch to a closed side fails the peer's request with CONNECTION_CLOSED and silently
    drops the peer's notify; the closed side's handlers are never invoked (SDK-defined)."""
    client, server = create_direct_dispatcher_pair()
    crec, srec = Recorder(), Recorder()
    c_req, c_notify = echo_handlers(crec)
    s_req, s_notify = echo_handlers(srec)
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, c_req, c_notify)
            await tg.start(server.run, s_req, s_notify)
            client.close()
            with pytest.raises(MCPError) as exc:
                await server.send_raw_request("roots/list", None)
            assert exc.value.error.code == CONNECTION_CLOSED
            await server.notify("notifications/message", None)
            server.close()
    assert crec.requests == []
    assert crec.notifications == []


@pytest.mark.anyio
async def test_direct_inbound_to_closed_never_run_peer_fails_with_connection_closed():
    """A peer that closed without ever running refuses dispatch instead of parking the caller."""
    client, server = create_direct_dispatcher_pair()
    c_req, c_notify = echo_handlers(Recorder())
    server.close()
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, c_req, c_notify)
            with pytest.raises(MCPError) as exc:
                await client.send_raw_request("ping", None)
            assert exc.value.error.code == CONNECTION_CLOSED
            client.close()


@pytest.mark.anyio
async def test_direct_send_raw_request_and_notify_raise_runtimeerror_when_no_peer_connected():
    d = DirectDispatcher(TransportContext(kind="direct", can_send_request=True))
    with pytest.raises(RuntimeError, match="no peer"):
        await d.send_raw_request("ping", None)
    with pytest.raises(RuntimeError, match="no peer"):
        await d.notify("ping", None)


@pytest.mark.anyio
async def test_direct_close_makes_run_return():
    client, server = create_direct_dispatcher_pair()
    on_request, on_notify = echo_handlers(Recorder())
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.run, on_request, on_notify)
            tg.start_soon(client.run, on_request, on_notify)
            client.close()
            server.close()


if TYPE_CHECKING:
    _d: Dispatcher[TransportContext] = DirectDispatcher(TransportContext(kind="direct", can_send_request=True))
    _o: Outbound = _d
