"""A connection's era is decided by the wire, in wire order, on any scheduler.

Every scenario here drives a lowlevel `Server` through the public entrypoint -
`Server.run(read_stream, write_stream)` - over in-memory anyio object streams carrying raw
`SessionMessage` frames. There is no client-side dispatcher in the loop: the test writes
exactly the frames a client would put on stdin and reads exactly the frames the server writes
to stdout, so the assertions are about the wire and nothing else.

The whole file is parametrized over the `asyncio` AND `trio` anyio backends. trio reorders
each batch of runnable tasks at random; an era decision that depends on which of two
in-flight tasks runs first is intermittently red here. A decision made in wire order - in the
read loop, before any `await` - is green on both, every time. This suite cannot tell read-loop
admission from a well-behaved spawned prologue, so it is the regression tripwire for anything
that puts an `await` in front of the era decision, not the proof of the ordering guarantee.

Scenarios:

- pipelined contradictory openers, in both orders: the FIRST frame's era wins;
- an enveloped request followed immediately by an envelope-less notification while the request
  is in flight: the notification is handled under the modern era, never dropped as
  pre-initialization traffic;
- a stray leading notification then a modern request: the client is not pinned legacy;
- `server/discover` then a fallback `initialize`: the handshake is still available;
- a legacy `initialize` arriving while a modern `tools/call` sleeps: -32022, call completes;
- a modern `tools/call` cancelled by `notifications/cancelled`: no further frame for that id,
  connection still alive.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INVALID_REQUEST,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    CallToolRequestParams,
    CallToolResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    RequestId,
    TextContent,
    Tool,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from mcp.server import Server, ServerRequestContext
from mcp.shared.message import SessionMessage

pytestmark = pytest.mark.anyio

Ctx = ServerRequestContext[dict[str, Any], Any]

# The modern per-request envelope. The spec's required pair (protocolVersion +
# clientCapabilities) plus the optional clientInfo, so a still-vendored
# clientInfo-required schema cannot turn these ordering tests into a schema debate.
MODERN_ENVELOPE: dict[str, Any] = {
    PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
    CLIENT_INFO_META_KEY: {"name": "ordering-suite", "version": "0"},
    CLIENT_CAPABILITIES_META_KEY: {},
}

# A client-shaped notification a conforming 2026 client may send at any time; it must
# never be read as an era-opening frame.
STRAY_NOTIFICATION_METHOD = "notifications/roots/list_changed"

# The custom notification the suite uses to prove a notification reached its handler.
NOTE_METHOD = "notifications/test/note"

# Buffer both directions so a pipelined burst never blocks the writer: pipelining is
# expressed with `send_nowait`, which cannot yield to the scheduler between frames.
FRAME_BUFFER = 64

# MUST-NOT-send is only observable as absence: watch the wire for this long after a
# peer cancel before also flushing with a follow-up request. An observation window, not
# a synchronization primitive.
CANCEL_SILENCE_WINDOW = 1.0

# Fresh connections for the scheduler-sensitivity stress test. An era decision that
# depends on which of two runnable tasks the scheduler picks first is answered wrongly on
# roughly half of them, so 25 connections make a single accidentally-green run vanishingly
# unlikely, while costing a wire-ordered decision a few milliseconds each.
OPENING_ATTEMPTS = 25

_SLOW_TOOL = Tool(name="slow", description="Blocks until released.", input_schema={"type": "object"})


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """Run every test in this module on both anyio backends: the trio scheduler is the
    load-bearing half of this suite (see the module docstring)."""
    return request.param


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


# --- the server under test ------------------------------------------------------------


@dataclass
class Probe:
    """Per-connection observation points; created inside the running backend."""

    entered: anyio.Event = field(default_factory=anyio.Event)
    """The `slow` tool handler has started: a modern request is genuinely in flight."""

    release: anyio.Event = field(default_factory=anyio.Event)
    """Lets the parked `slow` tool return its result."""

    noted: anyio.Event = field(default_factory=anyio.Event)
    """The `notifications/test/note` notification reached its handler."""


def make_server(probe: Probe) -> Server[dict[str, Any]]:
    """A dual-era lowlevel server with a fast `tools/list`, a `slow`
    tool that parks on `probe.release`, and a handler for the suite's custom notification."""

    async def list_tools(ctx: Ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[_SLOW_TOOL])

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "slow"
        probe.entered.set()
        await probe.release.wait()
        return CallToolResult(content=[TextContent(type="text", text="done")])

    async def on_note(ctx: Ctx, params: NotificationParams) -> None:
        probe.noted.set()

    server: Server[dict[str, Any]] = Server(
        "stdio-ordering", version="0.0.0", on_list_tools=list_tools, on_call_tool=call_tool
    )
    server.add_notification_handler(NOTE_METHOD, NotificationParams, on_note)
    return server


# --- the raw frames a client writes -----------------------------------------------------


def modern_request(request_id: RequestId, method: str, **params: Any) -> JSONRPCRequest:
    """A 2026-era request: its own protocol envelope rides in `params._meta`."""
    return JSONRPCRequest(
        jsonrpc="2.0", id=request_id, method=method, params={**params, "_meta": dict(MODERN_ENVELOPE)}
    )


def legacy_initialize(request_id: RequestId) -> JSONRPCRequest:
    """The 2025-era opening handshake."""
    return JSONRPCRequest(
        jsonrpc="2.0",
        id=request_id,
        method="initialize",
        params={
            "protocolVersion": LATEST_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ordering-suite", "version": "0"},
        },
    )


def bare_notification(method: str, **params: Any) -> JSONRPCNotification:
    """An envelope-less client notification (notifications never carry the envelope)."""
    return JSONRPCNotification(jsonrpc="2.0", method=method, params=dict(params))


# --- the in-memory connection -----------------------------------------------------------


class Wire:
    """The client's end of one in-memory connection.

    `pipeline(...)` writes a burst back-to-back with no scheduler yield between frames, so
    the whole burst is on the wire before the server can answer any of it - the pipelined
    conditions the ordering scenarios need. Every frame the server writes is kept in
    `frames`, in arrival order, so a test can await answers in either order and inspect
    what else was written.
    """

    def __init__(
        self,
        to_server: MemoryObjectSendStream[SessionMessage | Exception],
        from_server: MemoryObjectReceiveStream[SessionMessage],
    ) -> None:
        self._to_server = to_server
        self._from_server = from_server
        self.frames: list[JSONRPCMessage] = []

    def pipeline(self, *messages: JSONRPCMessage) -> None:
        """Write frames back-to-back, atomically with respect to the scheduler."""
        for message in messages:
            self._to_server.send_nowait(SessionMessage(message=message))

    async def send(self, message: JSONRPCMessage) -> None:
        """Write one frame."""
        await self._to_server.send(SessionMessage(message=message))

    async def read_one(self) -> None:
        """Wait for the next frame the server writes and record it."""
        self.frames.append((await self._from_server.receive()).message)

    def answer_for(self, request_id: RequestId) -> JSONRPCResponse | JSONRPCError | None:
        """The response or error already written for `request_id`, if any."""
        for frame in self.frames:
            if isinstance(frame, JSONRPCResponse | JSONRPCError) and frame.id == request_id:
                return frame
        return None

    async def response_to(self, request_id: RequestId) -> JSONRPCResponse | JSONRPCError:
        """The response or error for `request_id`, reading frames (bounded) until it lands."""
        with anyio.fail_after(5):
            while (answer := self.answer_for(request_id)) is None:
                await self.read_one()
        return answer

    async def watch(self, window: float) -> None:
        """Record every frame the server writes during a bounded observation window.

        Absence is the only observable of a MUST-NOT-send property; this is that window
        (never a synchronization primitive - the caller flushes with a follow-up request).
        """
        with anyio.move_on_after(window):
            while True:
                await self.read_one()


@asynccontextmanager
async def running(server: Server[dict[str, Any]]) -> AsyncIterator[Wire]:
    """Serve `server` over one in-memory stream pair via the public `Server.run` driver and
    yield the client's `Wire`. The connection ends by cancelling the driver, as a stdio
    process ending does; a failure raised inside the block surfaces unwrapped."""
    to_server_send, to_server_recv = anyio.create_memory_object_stream[SessionMessage | Exception](FRAME_BUFFER)
    from_server_send, from_server_recv = anyio.create_memory_object_stream[SessionMessage](FRAME_BUFFER)
    body_error: BaseException | None = None
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.run, to_server_recv, from_server_send, server.create_initialization_options())
            try:
                yield Wire(to_server_send, from_server_recv)
            except BaseException as exc:
                body_error = exc
            tg.cancel_scope.cancel()
    finally:
        to_server_send.close()
        to_server_recv.close()
        from_server_send.close()
        from_server_recv.close()
    if body_error is not None:
        raise body_error


async def test_wire_harness_relays_a_failing_body_exception_unwrapped() -> None:
    """The wire harness's own contract, pinned so its coverage stays whole: a failure raised
    inside a connection block surfaces as itself rather than as the driver task's exception
    group, so a red test always reads as the assertion that failed."""

    class _BodyFailed(Exception):
        pass

    server = make_server(Probe())
    with pytest.raises(_BodyFailed):
        async with running(server):
            raise _BodyFailed


# --- (1) pipelined contradictory openers -------------------------------------------------


async def test_modern_opener_pipelined_before_a_legacy_handshake_opens_modern() -> None:
    """Contradictory openers written back-to-back, modern first: the FIRST frame's era
    wins, so the enveloped request is served and the handshake behind it is refused with
    -32022 naming the modern versions. The era is a property of how the client opened the
    connection, never of which request happens to finish (or start) first."""
    server = make_server(Probe())
    async with running(server) as wire:
        wire.pipeline(modern_request(1, "tools/list"), legacy_initialize(2))
        tools = await wire.response_to(1)
        init = await wire.response_to(2)
    assert isinstance(tools, JSONRPCResponse), f"the modern opener must be served, got {tools}"
    assert tools.result["tools"][0]["name"] == "slow"
    assert isinstance(init, JSONRPCError), f"the handshake pipelined behind a modern opener must be refused, got {init}"
    assert init.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert LATEST_MODERN_VERSION in init.error.data["supported"]


async def test_legacy_handshake_pipelined_before_a_modern_request_opens_legacy() -> None:
    """Contradictory openers written back-to-back, handshake first: the FIRST frame's era
    wins, so the handshake is ACCEPTED even though a modern-enveloped request already sits
    on the wire behind it. What that pipelined request receives is the separate
    legacy-commitment ruling, pinned by
    `test_modern_request_on_a_legacy_committed_connection_is_refused_not_downgraded`."""
    server = make_server(Probe())
    async with running(server) as wire:
        wire.pipeline(legacy_initialize(1), modern_request(2, "tools/list"))
        init = await wire.response_to(1)
        # Drain the pipelined request: every request is owed an answer, but its content is
        # not era-diagnostic here (a legacy-served tools/list and a modern one look alike).
        await wire.response_to(2)
    assert isinstance(init, JSONRPCResponse), f"the handshake that opened the connection must be accepted, got {init}"
    assert init.result["protocolVersion"] == LATEST_HANDSHAKE_VERSION


async def test_modern_request_on_a_legacy_committed_connection_is_refused_not_downgraded() -> None:
    """Once the handshake has committed the connection to the legacy era, a request that
    claims the modern era in its envelope is refused with INVALID_REQUEST rather than
    silently served under legacy semantics: a second, conflicting era claim on a committed
    connection is a client error, so the answer is the deterministic refusal, never the
    era-ambiguous pass-through."""
    server = make_server(Probe())
    async with running(server) as wire:
        await wire.send(legacy_initialize(1))
        init = await wire.response_to(1)
        assert isinstance(init, JSONRPCResponse), f"handshake must be accepted, got {init}"
        await wire.send(bare_notification("notifications/initialized"))
        await wire.send(modern_request(2, "tools/list"))
        answer = await wire.response_to(2)
    assert isinstance(answer, JSONRPCError), (
        f"an enveloped request on a legacy-committed connection must be refused, not served; got {answer}"
    )
    assert answer.error.code == INVALID_REQUEST


async def test_pipelined_openers_are_ordered_by_the_wire_not_the_scheduler() -> None:
    """The modern-first opener pair over many fresh connections. An era decision that
    depends on which of two runnable tasks the scheduler picks first accepts the handshake
    on some connections and refuses it on others; a decision made in wire order refuses it
    on every one. One flipped connection fails the test - this is the scheduler-sensitivity
    detector (see the module docstring for what it can and cannot prove)."""
    for attempt in range(OPENING_ATTEMPTS):
        server = make_server(Probe())
        async with running(server) as wire:
            wire.pipeline(modern_request(1, "tools/list"), legacy_initialize(2))
            init = await wire.response_to(2)
            await wire.response_to(1)
        assert isinstance(init, JSONRPCError) and init.error.code == UNSUPPORTED_PROTOCOL_VERSION, (
            f"connection {attempt}: the handshake pipelined behind a modern opener was answered {init}; "
            "the era followed the task scheduler, not the wire order"
        )


# --- (2) a notification pipelined behind an in-flight modern request ---------------------


async def test_notification_pipelined_behind_an_in_flight_modern_request_is_delivered() -> None:
    """A modern-enveloped request followed immediately by an envelope-less notification:
    the request opened the modern era, so the notification is handled under that era -
    never dropped as "received before initialization", which is the fate a legacy-era
    misroute would give it while the request is still in flight."""
    probe = Probe()
    server = make_server(probe)
    async with running(server) as wire:
        wire.pipeline(
            modern_request(1, "tools/call", name="slow", arguments={}),
            bare_notification(NOTE_METHOD),
        )
        with anyio.fail_after(5):
            await probe.entered.wait()  # the modern request is genuinely in flight...
            await probe.noted.wait()  # ...and the notification behind it reached its handler
        probe.release.set()
        result = await wire.response_to(1)
    assert isinstance(result, JSONRPCResponse), (
        f"the in-flight modern request must still complete after the notification, got {result}"
    )
    assert result.result["content"][0]["text"] == "done"


# --- (3) a stray leading notification does not decide the era ------------------------------


async def test_stray_leading_notification_does_not_pin_the_connection_legacy() -> None:
    """A leading `notifications/roots/list_changed` (a courtesy frame a conforming 2026
    client may send) must not open the legacy era: the modern request that follows opens the
    MODERN era - proven by its being served AND by a later handshake being refused -32022 -
    instead of the client being stranded behind an error on every request thereafter."""
    server = make_server(Probe())
    async with running(server) as wire:
        await wire.send(bare_notification(STRAY_NOTIFICATION_METHOD))
        await wire.send(modern_request(1, "tools/list"))
        tools = await wire.response_to(1)
        assert isinstance(tools, JSONRPCResponse), (
            f"the modern request after a stray notification must be served, got {tools}"
        )
        assert tools.result["tools"][0]["name"] == "slow"
        await wire.send(legacy_initialize(2))
        init = await wire.response_to(2)
    assert isinstance(init, JSONRPCError), (
        f"the modern request must have opened the MODERN era (a later handshake is refused), got {init}"
    )
    assert init.error.code == UNSUPPORTED_PROTOCOL_VERSION


# --- (4) probe-then-fallback ---------------------------------------------------------------


async def test_discover_probe_leaves_the_initialize_fallback_available() -> None:
    """`server/discover` is a probe, not an opening: it is answered from the real modern
    surface but commits nothing, so a client that probes and then falls back to `initialize`
    (the stdio spec's backward-compatibility flow) completes the handshake instead of being
    told -32022 - the one code that means "server is modern, do not fall back"."""
    server = make_server(Probe())
    async with running(server) as wire:
        await wire.send(modern_request(1, "server/discover"))
        discover = await wire.response_to(1)
        assert isinstance(discover, JSONRPCResponse), f"the probe must be answered, got {discover}"
        assert "capabilities" in discover.result
        await wire.send(legacy_initialize(2))
        init = await wire.response_to(2)
    assert isinstance(init, JSONRPCResponse), f"the fallback handshake after a probe must be accepted, got {init}"
    assert init.result["protocolVersion"] == LATEST_HANDSHAKE_VERSION


# --- (5) a legacy handshake arriving during in-flight modern work -----------------------


async def test_legacy_handshake_during_an_in_flight_modern_call_is_refused_and_the_call_completes() -> None:
    """A connection already executing modern work is a modern connection: a handshake
    arriving mid-flight is refused -32022 naming the modern versions - it is never accepted
    and locked legacy underneath the running request - and the modern call still completes
    with its own result afterwards."""
    probe = Probe()
    server = make_server(probe)
    async with running(server) as wire:
        await wire.send(modern_request(1, "tools/call", name="slow", arguments={}))
        with anyio.fail_after(5):
            await probe.entered.wait()  # modern work is in flight
        await wire.send(legacy_initialize(2))
        init = await wire.response_to(2)
        assert isinstance(init, JSONRPCError), f"a handshake during in-flight modern work must be refused, got {init}"
        assert init.error.code == UNSUPPORTED_PROTOCOL_VERSION
        assert LATEST_MODERN_VERSION in init.error.data["supported"]
        probe.release.set()
        result = await wire.response_to(1)
    assert isinstance(result, JSONRPCResponse), (
        f"the modern call must complete after the refused handshake, got {result}"
    )
    assert result.result["content"][0]["text"] == "done"


# --- (6) peer cancel: no further frame, connection alive ---------------------------------


async def test_cancelled_modern_call_writes_no_further_frame_and_the_connection_survives() -> None:
    """A modern `tools/call` cancelled by the peer with `notifications/cancelled`: no frame
    for that id is written afterwards (the stdio spec: the server MUST NOT send any further
    messages for a cancelled request - so no `{"code":0,"message":"Request cancelled"}`
    echo), and the connection keeps serving the request that follows."""
    probe = Probe()
    server = make_server(probe)
    async with running(server) as wire:
        await wire.send(modern_request(1, "tools/call", name="slow", arguments={}))
        with anyio.fail_after(5):
            await probe.entered.wait()
        await wire.send(bare_notification("notifications/cancelled", requestId=1, reason="test"))
        await wire.watch(CANCEL_SILENCE_WINDOW)
        # The connection is alive: a following modern request is served. Its answer also
        # flushes onto the record any frame the server wrote for the cancelled id first.
        await wire.send(modern_request(2, "tools/list"))
        followup = await wire.response_to(2)
    assert wire.answer_for(1) is None, (
        f"no frame may be written for a cancelled request, but the server wrote {wire.answer_for(1)}"
    )
    assert isinstance(followup, JSONRPCResponse), f"the connection must keep serving after a cancel, got {followup}"
    assert followup.result["tools"][0]["name"] == "slow"
