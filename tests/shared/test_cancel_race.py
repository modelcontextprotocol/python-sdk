"""Cancellation races on the wire: what `JSONRPCDispatcher` writes when a peer's cancel, a
handler's completion, and connection teardown collide.

The dispatcher's silence after a peer cancel is a property of the request's reply channel,
not a check before writing: a peer cancel (read while the request is still cancellable), the
request's own terminal write and a gone peer each swap the channel's write target for a
void. A body that has returned is committed - the request leaves the cancellable table
before its answer spends the channel, with no checkpoint between - so a cancel read after
that finds nothing to interrupt and the owed answer is written. These tests pin that
behaviour at the wire, in the races where a design could differ, on both anyio backends
(module `anyio_backend` fixture). Synchronisation is by events, by
`anyio.wait_all_tasks_blocked()` (a scheduler quiesce, not a sleep), and by reading the wire
until a fence frame lands; no fixed sleep is any test's only synchronisation.

The scenarios and what each proves:

1. A `subscriptions/listen`-shaped request emitting stamped notifications is peer
   cancelled; the handler's own cleanup tries to emit one more stamped event after the
   cancel was read. The straggler never follows the cancel (the request's back-channel
   is revoked at cancel-read), no answer is owed for the withdrawn id, and the connection
   keeps serving.
2. The completed-just-as-cancelled window, order Y (the handler RETURNED its result
   before the cancel is read): the result write is parked on transport backpressure when
   the cancel is read and processed, and only afterwards does anyone drain the wire. An
   answer already computed when the cancel is read is written exactly once: the request
   retired from the cancellable table before its write, so the racing cancel finds nothing
   to interrupt.
3. The same window, order X (the cancel is READ first, the handler completes anyway
   because the cancel doubles as its wakeup and the interruption is deferred), over a
   transport that accepts a frame without a checkpoint. The result was produced after the
   cancel took effect and must not reach the wire on any transport: the cancel revoked the
   channel, so the answer writes into the void whether or not the transport checkpoints.
4. Shutdown while a handler is mid-run: stdin EOF (peer gone, nothing owed on the wire),
   an owner-initiated teardown with the peer still connected (exactly one
   CONNECTION_CLOSED error, never a duplicate), a teardown landing on a parked answer
   write (at most one answer for the id), and a teardown after a peer cancel of a handler
   that outlives its interruption (no frame for the withdrawn id).

Together these are the cancellation rulings this SDK ships: an owed result is written; no
message follows for a cancelled id; at most one answer per id. A red test is a behavioural
regression, and the failure message prints the frames written so the difference is legible
from the output.
"""

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

import anyio
import pytest
from mcp_types import (
    CONNECTION_CLOSED,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)

from mcp.shared.dispatcher import DispatchContext
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext

DCtx = DispatchContext[TransportContext]

WAIT = 5
"""Bound (seconds) on any wait for a frame or an event, so a hang fails instead of stalling."""

LISTEN_METHOD = "subscriptions/listen"
EVENT_METHOD = "notifications/gate/event"

CONNECTION_CLOSED_ERROR = ErrorData(code=CONNECTION_CLOSED, message="Connection closed")
"""The one answer a live peer gets for a request the owner tears down mid-run."""


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """Run every test in this module on both anyio backends: several of these races only
    show on the shuffled scheduler."""
    return request.param


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


class RecordingWriteStream:
    """A transport that accepts each frame synchronously - `send` has no checkpoint - and
    records it. The completed-answer race turns on whether the transport hands the frame off
    before the writer's next checkpoint, so this is the accept-immediately extreme; the
    zero-buffer memory stream in the backpressure tests is the parked extreme."""

    def __init__(self) -> None:
        self.sent: list[SessionMessage] = []

    async def send(self, item: SessionMessage) -> None:
        self.sent.append(item)

    async def aclose(self) -> None:
        raise NotImplementedError  # the dispatcher releases the stream via __aexit__, never aclose

    async def __aenter__(self) -> "RecordingWriteStream":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return None

    @property
    def frames(self) -> list[JSONRPCMessage]:
        return [item.message for item in self.sent]


def request(request_id: RequestId, method: str, **params: Any) -> SessionMessage:
    return SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params=dict(params)))


def cancel(request_id: RequestId) -> SessionMessage:
    return SessionMessage(
        message=JSONRPCNotification(jsonrpc="2.0", method="notifications/cancelled", params={"requestId": request_id})
    )


def answers_for(frames: list[JSONRPCMessage], request_id: RequestId) -> list[JSONRPCMessage]:
    """Every response or error frame written for `request_id`, in wire order."""
    return [f for f in frames if isinstance(f, JSONRPCResponse | JSONRPCError) and f.id == request_id]


@dataclass
class CancelWatch:
    """`on_notify` admission that flags the instant a `notifications/cancelled` is READ.

    A dispatcher admits notifications synchronously in receive order, after its own cancel
    handling for that frame has run, so `read` fires exactly once the cancel has taken
    effect (the request's channel is revoked and its scope interrupted) - the fence the
    races below hang off, with no sleep."""

    read: anyio.Event = field(default_factory=anyio.Event)

    def __call__(self, ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> Awaitable[None]:
        # The peer in these races sends the owner one notification: the cancel it watches for.
        assert method == "notifications/cancelled", f"cancel-race gate admitted an unexpected {method!r}"
        self.read.set()
        return self._ignore()

    async def _ignore(self) -> None:
        pass


# --- 1. a stamped listen event racing the peer's cancel ---------------------------------


@pytest.mark.anyio
async def test_stamped_listen_event_emitted_after_the_cancel_is_read_never_follows_it() -> None:
    """A `subscriptions/listen`-shaped request streams stamped events; the peer cancels it;
    the handler's own cleanup then tries to emit one final stamped event AFTER the cancel
    was read (a shielded straggler - the strongest form of the race, since an emit merely
    interrupted mid-write is silenced by the scope cancel in any design). The event stamped
    before the cancel is legitimately on the wire; the straggler must never follow the
    cancel, no answer is owed for the withdrawn id, and the connection keeps serving."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    recording = RecordingWriteStream()
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, recording)
    watch = CancelWatch()
    first_event_sent = anyio.Event()
    cleanup_ran = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "probe":
            return {"probe": True}
        assert method == LISTEN_METHOD
        try:
            # A stamped event: the dispatch context routes it with the listen's
            # related_request_id so a stream transport can associate it.
            await ctx.notify(EVENT_METHOD, {"seq": 1})
            first_event_sent.set()
            await anyio.sleep_forever()
        finally:
            # The straggler: cleanup emitting one last stamped event once the
            # cancel has already been read. Shielded, so only the design's
            # silence rule (revoked channel / closed context) can drop it.
            with anyio.CancelScope(shield=True):
                await ctx.notify(EVENT_METHOD, {"seq": 2})
            cleanup_ran.set()
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, LISTEN_METHOD, notifications={}))
            with anyio.fail_after(WAIT):
                await first_event_sent.wait()
            await read_send.send(cancel(1))
            with anyio.fail_after(WAIT):
                await watch.read.wait()
                await cleanup_ran.wait()
            # Fence: a request admitted after the cancel is answered, so the record below
            # is the complete post-cancel wire, not an observation window.
            await read_send.send(request(2, "probe"))
            with anyio.fail_after(WAIT):
                while not answers_for(recording.frames, 2):
                    await anyio.wait_all_tasks_blocked()
            read_send.close()  # EOF: run() drains, cancels and returns; the tg then exits.
    finally:
        read_send.close()
        read_recv.close()

    stamped = [
        (item.message, item.metadata)
        for item in recording.sent
        if isinstance(item.message, JSONRPCNotification) and item.message.method == EVENT_METHOD
    ]
    assert [event.params for event, _ in stamped] == [{"seq": 1}], (
        f"only the event sent before the cancel may reach the wire, got {[event for event, _ in stamped]}"
    )
    stamp = stamped[0][1]
    assert isinstance(stamp, ServerMessageMetadata), f"a listen event carries the listen's metadata, got {stamp}"
    assert stamp.related_request_id == 1, f"the event is stamped with the listen's id, got {stamp}"
    assert answers_for(recording.frames, 1) == [], (
        f"no answer is owed for the withdrawn listen, but the wire holds {answers_for(recording.frames, 1)}"
    )
    assert answers_for(recording.frames, 2) == [JSONRPCResponse(jsonrpc="2.0", id=2, result={"probe": True})], (
        "the connection must carry on serving after the cancel"
    )


# --- 2. completed-just-as-cancelled, order Y: the owed answer under backpressure ---------


async def _owed_answer_under_backpressure() -> list[JSONRPCMessage]:
    """Order Y with the transport under backpressure, deterministically.

    The handler returns its result BEFORE the cancel is read, and its result write parks on
    a zero-buffer stream (nobody is draining yet). The peer's cancel is then read and its
    handling is allowed to run to quiescence, and only then does the peer drain the wire,
    finishing with a probe whose answer fences the record. Returns every frame written."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, write_send)
    watch = CancelWatch()
    release = anyio.Event()
    returned: list[dict[str, Any]] = []
    frames: list[JSONRPCMessage] = []

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "probe":
            return {"probe": True}
        await release.wait()
        answer = {"answer": 42}
        returned.append(answer)  # no checkpoint after this: the answer is computed and owed
        return answer

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "slow"))
            await anyio.wait_all_tasks_blocked()  # the handler is parked on `release`
            release.set()
            # The handler returns and its result write parks on the zero-buffer stream,
            # BEFORE the cancel exists: this is what makes the ordering Y and not X.
            await anyio.wait_all_tasks_blocked()
            assert returned == [{"answer": 42}], "precondition: the handler completed before the cancel was sent"
            await read_send.send(cancel(1))
            with anyio.fail_after(WAIT):
                await watch.read.wait()
            # Let the dispatcher finish reacting to the cancel (a design that aborts the
            # parked write unwinds it here) before any reader appears on the transport.
            await anyio.wait_all_tasks_blocked()
            await read_send.send(request(2, "probe"))
            with anyio.fail_after(WAIT):
                while not answers_for(frames, 2):
                    frames.append((await write_recv.receive()).message)
            read_send.close()  # EOF; run() returns and the task group exits
        with anyio.move_on_after(WAIT):
            # Anything written during teardown (there should be nothing).
            frames.extend([item.message async for item in write_recv])
    finally:
        for stream in (read_send, read_recv, write_send, write_recv):
            stream.close()
    return frames


@pytest.mark.anyio
async def test_answer_returned_before_the_cancel_is_read_is_written_despite_transport_backpressure() -> None:
    """The completed-just-as-cancelled edge, order Y: an answer the handler already computed
    when the cancel is read is written, exactly once - here with the answer's write parked on
    a stalled transport, so the dispatcher's cancel handling and the transport's acceptance
    genuinely race. The request retired from the cancellable table before its write, so the
    racing cancel finds nothing to interrupt and the parked answer is delivered when the
    peer drains; a design that keeps the request cancellable until the write completes would
    let the cancel interrupt the parked write and drop the owed answer."""
    frames = await _owed_answer_under_backpressure()
    owed = answers_for(frames, 1)
    assert owed == [JSONRPCResponse(jsonrpc="2.0", id=1, result={"answer": 42})], (
        "the handler returned {'answer': 42} before the cancel was read; the owed answer must "
        f"reach the wire exactly once, but the answers for id 1 were {owed} (full wire: {frames})"
    )
    assert answers_for(frames, 2) == [JSONRPCResponse(jsonrpc="2.0", id=2, result={"probe": True})]


# --- 3. completed-just-as-cancelled, order X: the revoked channel over a sync transport ---


async def _completion_after_the_cancel_over_a_sync_transport() -> list[JSONRPCMessage]:
    """Order X over a transport that accepts frames without a checkpoint.

    The cancel is READ while the handler is parked on the peer's own signal, so the
    dispatcher's cancel handling runs with the request still cancellable (channel revoked
    and scope interrupted). The handler nonetheless completes: the cancel signal is also its
    wakeup, so the interruption is deferred past its return. What reaches the recording
    transport is exactly what the dispatcher writes when a body returns AFTER its cancel
    took effect and no transport checkpoint stands in the way. Returns every frame written."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    recording = RecordingWriteStream()
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, recording)
    watch = CancelWatch()
    handler_started = anyio.Event()
    handler_returned = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "probe":
            return {"probe": True}
        handler_started.set()
        await ctx.cancel_requested.wait()  # the cancel is this handler's wakeup
        handler_returned.set()
        return {"completed": "after-cancel"}

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "slow"))
            with anyio.fail_after(WAIT):
                await handler_started.wait()
            await read_send.send(cancel(1))
            with anyio.fail_after(WAIT):
                await watch.read.wait()
                await handler_returned.wait()
            await anyio.wait_all_tasks_blocked()
            await read_send.send(request(2, "probe"))
            with anyio.fail_after(WAIT):
                while not answers_for(recording.frames, 2):
                    await anyio.wait_all_tasks_blocked()
            read_send.close()
    finally:
        read_send.close()
        read_recv.close()
    return recording.frames


@pytest.mark.anyio
async def test_answer_produced_after_the_cancel_took_effect_never_reaches_a_no_checkpoint_transport() -> None:
    """stdio.mdx: a server MUST NOT send any further messages for a cancelled request. Here
    the cancel took effect (was read and applied) BEFORE the handler produced its result;
    that result is a further message for a cancelled request and must not reach the wire,
    regardless of whether the transport happens to checkpoint before accepting a frame. The
    recording transport accepts without a checkpoint, so only a design whose silence lives
    in the write path itself (a revoked channel) drops it; a design whose silence is 'the
    scope cancel interrupts the write' leaks it, because there is no checkpoint to interrupt."""
    frames = await _completion_after_the_cancel_over_a_sync_transport()
    assert answers_for(frames, 1) == [], (
        f"the result was produced after the cancel took effect and must not follow it, but the "
        f"wire holds {answers_for(frames, 1)} (full wire: {frames})"
    )
    assert answers_for(frames, 2) == [JSONRPCResponse(jsonrpc="2.0", id=2, result={"probe": True})]


# --- 2b. the same window with a live drain: measured across fresh connections -----------

REPEATS = 20
"""Fresh connections for the live-drain race. With a reader draining the wire, the
completed answer is usually accepted before any cancel handling can withdraw it, so this
scenario is a distribution, not a certainty: the invariant asserted is that whatever
happens is legal (at most one answer for the id, and it is the handler's result), and the
delivery ratio is printed for the record."""


async def _completion_racing_the_cancel_with_a_live_drain() -> list[JSONRPCMessage]:
    """The handler returns at the instant the cancel arrives, while a reader drains the wire.

    `release` and the cancel are made available in the same scheduler step, so which the
    dispatcher acts on first is the backend's choice (deterministic FIFO on asyncio, shuffled
    on trio) - the honest live-transport version of the race. Returns every frame written."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, write_send)
    watch = CancelWatch()
    release = anyio.Event()
    frames: list[JSONRPCMessage] = []

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "probe":
            return {"probe": True}
        await release.wait()
        return {"answer": 42}

    def record(item: SessionMessage) -> None:
        frames.append(item.message)  # incremental: the probe fence polls `frames` while draining

    async def drain() -> None:
        async for item in write_recv:
            record(item)

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(drain)
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "slow"))
            await anyio.wait_all_tasks_blocked()  # handler parked on `release`, reader parked draining
            # Same step, no yield between: the handler's wakeup and the cancel's arrival race.
            release.set()
            read_send.send_nowait(cancel(1))
            with anyio.fail_after(WAIT):
                await watch.read.wait()
            await anyio.wait_all_tasks_blocked()
            await read_send.send(request(2, "probe"))
            with anyio.fail_after(WAIT):
                while not answers_for(frames, 2):
                    await anyio.wait_all_tasks_blocked()
            read_send.close()  # EOF; run() closes the write stream, which ends `drain`
    finally:
        for stream in (read_send, read_recv, write_send, write_recv):
            stream.close()
    return frames


@pytest.mark.anyio
async def test_completion_racing_the_cancel_with_a_live_reader_is_legal_on_every_connection() -> None:
    """Across many fresh connections, the handler's result and the peer's cancel race with a
    reader draining the wire. Either outcome is legal for the peer (cancellation.mdx: the
    server MAY ignore a cancel whose processing already completed; a raced peer ignores a late
    answer). What is never legal: two answers for one id, an error for the withdrawn id, or a
    result other than the handler's. This test asserts only the invariants; the
    delivered/dropped split it prints records which way the live race falls."""
    only_legal = [JSONRPCResponse(jsonrpc="2.0", id=1, result={"answer": 42})]
    delivered = 0
    for attempt in range(REPEATS):
        frames = await _completion_racing_the_cancel_with_a_live_drain()
        owed = answers_for(frames, 1)
        # At most one answer for the id, and if any it is the handler's result: `[]` (the cancel
        # won the race) and `only_legal` (the answer won) are the two legal wires.
        assert owed in ([], only_legal), (
            f"attempt {attempt}: id 1 may carry nothing or exactly its result {only_legal}, got {owed} "
            f"(full wire: {frames})"
        )
        delivered += len(owed)
        assert answers_for(frames, 2) == [JSONRPCResponse(jsonrpc="2.0", id=2, result={"probe": True})], (
            f"attempt {attempt}: the connection must keep serving, wire: {frames}"
        )
    # Recorded, not asserted: which way the live race falls is the scheduler's choice.
    print(f"live-drain race delivered the completed answer {delivered}/{REPEATS}")


# --- 4. shutdown while a handler is mid-run ---------------------------------------------


@pytest.mark.anyio
async def test_stdin_eof_mid_handler_writes_nothing_and_leaves_no_duplicate() -> None:
    """The peer's input ends (it is gone) while a handler runs: the request is interrupted
    and nothing is written for it - there is nobody left to read a CONNECTION_CLOSED answer,
    and a frame onto a wire nobody reads is exactly what the peer-gone mode forbids."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    recording = RecordingWriteStream()
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, recording)
    watch = CancelWatch()
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_cancelled.set()
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "slow"))
            with anyio.fail_after(WAIT):
                await handler_started.wait()
            read_send.close()  # EOF while the handler runs
            with anyio.fail_after(WAIT):
                await handler_cancelled.wait()
    finally:
        read_send.close()
        read_recv.close()
    assert answers_for(recording.frames, 1) == [], (
        f"at EOF the peer is gone: nothing may be written for the interrupted request, got {recording.frames}"
    )


@pytest.mark.anyio
async def test_owner_teardown_mid_handler_answers_the_live_peer_exactly_once() -> None:
    """The owner tears the connection down (cancels the dispatcher's task) while a handler
    runs and the peer is still connected: the interrupted request gets exactly one
    CONNECTION_CLOSED error so the peer isn't left waiting - one answer, never two, and
    never a result the handler didn't return."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    recording = RecordingWriteStream()
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, recording)
    watch = CancelWatch()
    handler_started = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await anyio.sleep_forever()
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "slow"))
            with anyio.fail_after(WAIT):
                await handler_started.wait()
            tg.cancel_scope.cancel()  # owner teardown; the read side is still open (peer alive)
    finally:
        read_send.close()
        read_recv.close()
    assert answers_for(recording.frames, 1) == [JSONRPCError(jsonrpc="2.0", id=1, error=CONNECTION_CLOSED_ERROR)], (
        f"an interrupted request whose peer is still there gets exactly one CONNECTION_CLOSED, got {recording.frames}"
    )


@pytest.mark.anyio
async def test_owner_teardown_landing_on_a_parked_answer_write_never_stacks_a_second_answer() -> None:
    """The handler has returned and its result write is parked on a stalled transport when
    the owner tears the connection down. The teardown must not stack a CONNECTION_CLOSED
    error on top of the started result write: whatever the peer eventually reads for the id
    is at most one answer, and if any answer surfaces it is the handler's result."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, write_send)
    watch = CancelWatch()
    returned = anyio.Event()
    frames: list[JSONRPCMessage] = []

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        returned.set()
        return {"answer": 42}

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "quick"))
            with anyio.fail_after(WAIT):
                await returned.wait()
            await anyio.wait_all_tasks_blocked()  # the result write is parked: nobody reads
            tg.cancel_scope.cancel()  # owner teardown lands on the parked write
        # run() has returned and closed its write stream; whatever survived is drainable now.
        with anyio.move_on_after(WAIT):
            frames.extend([item.message async for item in write_recv])
    finally:
        for stream in (read_send, read_recv, write_send, write_recv):
            stream.close()
    owed = answers_for(frames, 1)
    only_legal = [JSONRPCResponse(jsonrpc="2.0", id=1, result={"answer": 42})]
    assert owed in ([], only_legal), (
        f"one request id gets at most one answer, and it can only be the handler's result; teardown left {owed}"
    )


async def _teardown_after_a_peer_cancel_of_a_lingering_handler(*, via_eof: bool) -> list[JSONRPCMessage]:
    """The peer cancels a request whose handler shields its cleanup and so is still running
    when the connection is torn down - either by the peer's EOF or by the owner cancelling
    the driver with the peer still connected. Returns every frame written."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](8)
    recording = RecordingWriteStream()
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, recording)
    watch = CancelWatch()
    handler_started = anyio.Event()
    lingering = anyio.Event()
    finish_cleanup = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            # Cleanup that outlives the peer's interruption: the request is
            # withdrawn but its task lingers here when the teardown lands.
            with anyio.CancelScope(shield=True):
                lingering.set()
                await finish_cleanup.wait()
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, watch)
            await read_send.send(request(1, "slow"))
            with anyio.fail_after(WAIT):
                await handler_started.wait()
            await read_send.send(cancel(1))  # the peer withdraws id 1
            with anyio.fail_after(WAIT):
                await watch.read.wait()
                await lingering.wait()
            if via_eof:
                read_send.close()  # the peer goes away
            else:
                tg.cancel_scope.cancel()  # the owner tears down; the peer is still connected
            # No await from here: releasing the shield synchronously means the lingering
            # task meets the pending teardown at its very next checkpoint.
            finish_cleanup.set()
    finally:
        read_send.close()
        read_recv.close()
    return recording.frames


@pytest.mark.anyio
async def test_eof_after_a_peer_cancel_writes_nothing_for_the_withdrawn_id() -> None:
    """Control for the next test: with the peer gone (EOF), a withdrawn request whose task
    lingers past the interruption is torn down without any frame for its id."""
    frames = await _teardown_after_a_peer_cancel_of_a_lingering_handler(via_eof=True)
    assert answers_for(frames, 1) == [], f"the peer withdrew id 1 and is gone; teardown may not answer it, got {frames}"


@pytest.mark.anyio
async def test_owner_teardown_after_a_peer_cancel_writes_nothing_for_the_withdrawn_id() -> None:
    """The peer withdrew the request; its task lingers in shielded cleanup; the owner then
    tears the connection down while the peer is still connected. The withdrawal already
    happened, so the teardown must not resurrect an answer for that id: the cancel revoked
    the request's write target, leaving the shutdown arm nothing to write with. A design
    whose only shutdown guard is 'no answer written yet, and the peer is not gone' cannot see
    the withdrawal and writes a CONNECTION_CLOSED frame after the cancel."""
    frames = await _teardown_after_a_peer_cancel_of_a_lingering_handler(via_eof=False)
    assert answers_for(frames, 1) == [], (
        f"the peer withdrew id 1 before teardown; teardown may not answer it, got {frames}"
    )
