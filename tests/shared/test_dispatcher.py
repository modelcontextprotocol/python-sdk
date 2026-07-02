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
    ErrorData,
    RequestId,
    Tool,
)

from mcp.shared._compat import resync_tracer
from mcp.shared.direct_dispatcher import DirectDispatcher, create_direct_dispatcher_pair
from mcp.shared.dispatcher import DispatchContext, Dispatcher, OnNotify, OnRequest, Outbound
from mcp.shared.exceptions import MCPError
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
async def test_send_raw_request_reraises_mcperror_from_handler_unchanged(pair_factory: PairFactory):
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


@pytest.mark.anyio
async def test_send_raw_request_honors_caller_supplied_request_id_verbatim_typed(pair_factory: PairFactory):
    """A caller-supplied `CallOptions["request_id"]` reaches the peer's context verbatim —
    "7" stays a string, never the integer 7 — and the next call without one still mints
    a dispatcher id as before."""
    async with running_pair(pair_factory) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.send_raw_request("first", None, {"request_id": "7"})
            await client.send_raw_request("second", None)
    supplied, minted = (ctx.request_id for ctx in srec.contexts)
    assert supplied == "7"
    assert type(supplied) is str
    assert type(minted) is int


@pytest.mark.anyio
async def test_send_raw_request_with_in_flight_request_id_raises_and_frees_id_on_completion(
    pair_factory: PairFactory,
):
    """Reusing an id while it is in flight is a loud `ValueError` — silent reuse would
    corrupt response correlation. Once the first request completes, the id is free
    again: the reservation is in-flight-scoped, not permanent."""
    entered = anyio.Event()
    release = anyio.Event()

    async def parked(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {"served": method}

    async with running_pair(pair_factory, server_on_request=parked) as (client, *_):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:

                async def first() -> None:
                    await client.send_raw_request("slow", None, {"request_id": "listen-1"})

                tg.start_soon(first)
                await entered.wait()
                with pytest.raises(ValueError, match="already in flight"):
                    await client.send_raw_request("duplicate", None, {"request_id": "listen-1"})
                release.set()
            result = await client.send_raw_request("again", None, {"request_id": "listen-1"})
    assert result == {"served": "again"}


@pytest.mark.anyio
async def test_minted_ids_skip_a_caller_supplied_id_still_in_flight(pair_factory: PairFactory):
    """The dispatcher mints PAST a key a supplied id occupies — the collision error
    is reserved for the caller who chose the id, never an innocent minted request."""
    entered = anyio.Event()
    release = anyio.Event()
    seen_ids: list[RequestId | None] = []

    async def maybe_park(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        seen_ids.append(ctx.request_id)
        if method == "park":
            entered.set()
            await release.wait()
        return {}

    async with running_pair(pair_factory, server_on_request=maybe_park) as (client, *_):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:

                async def parked() -> None:
                    await client.send_raw_request("park", None, {"request_id": "3"})

                tg.start_soon(parked)
                await entered.wait()
                # The counter mints 1 and 2, then skips the occupied 3 to 4.
                for _ in range(3):
                    await client.send_raw_request("plain", None)
                release.set()
            assert [request_id for request_id in seen_ids if request_id != "3"] == [1, 2, 4]


@pytest.mark.anyio
async def test_supplied_numeric_string_id_collides_with_its_int_twin(pair_factory: PairFactory):
    """ "7" and 7 are one id in the collision domain on BOTH dispatchers, so the
    in-memory pair raises exactly where the wire dispatcher (whose pending keys
    are coerced for response correlation) would."""
    entered = anyio.Event()
    release = anyio.Event()

    async def parked(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {}

    async with running_pair(pair_factory, server_on_request=parked) as (client, *_):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:

                async def first() -> None:
                    await client.send_raw_request("slow", None, {"request_id": 7})

                tg.start_soon(first)
                await entered.wait()
                with pytest.raises(ValueError, match="already in flight"):
                    await client.send_raw_request("duplicate", None, {"request_id": "7"})
                release.set()
            # Completion frees the id for either spelling.
            assert await client.send_raw_request("again", None, {"request_id": "7"}) == {}


if TYPE_CHECKING:
    _d: Dispatcher[TransportContext] = DirectDispatcher(TransportContext(kind="direct", can_send_request=True))
    _o: Outbound = _d
