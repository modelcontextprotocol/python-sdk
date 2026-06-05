"""Tests for the stdio client transport.

Transport logic (framing, parse errors, shutdown escalation decisions) is tested in
process against a fake process injected through the spawn seam; only real OS behaviour
(process-group kill semantics, SIGKILL after an ignored SIGTERM, exec failure) uses
real subprocesses, synchronized only by kernel-level liveness sockets. The full
client<->server round trip is pinned by tests/interaction/transports/test_stdio.py.
"""

import errno
import gc
import logging
import math
import os
import signal
import sys
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import TextIO, cast

import anyio
import anyio.abc
import anyio.lowlevel
import pytest
import trio
import trio.testing
from anyio.streams.memory import MemoryObjectReceiveStream

from mcp.client import stdio
from mcp.client._transport import ReadStream
from mcp.client.session import ClientSession
from mcp.client.stdio import (
    _EXIT_POLL_INTERVAL,
    StdioServerParameters,
    _create_platform_compatible_process,
    _terminate_process_tree,
    stdio_client,
)
from mcp.os.posix import utilities as posix_utilities
from mcp.os.posix.utilities import terminate_posix_process_tree
from mcp.os.win32.utilities import FallbackProcess
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

# ---------------------------------------------------------------------------
# In-process fake of the spawned server process
# ---------------------------------------------------------------------------
#
# Everything between the spawn and the OS kill is pure SDK logic, so it is tested
# against this fake by monkeypatching the spawn and terminate seams. The OS half
# is tested separately below with real processes.


class _FakeStdin:
    """The fake process's stdin: records what the client writes, signals closure."""

    def __init__(self, process: "FakeProcess") -> None:
        self._process = process

    async def send(self, data: bytes) -> None:
        if self._process.stdin_send_gate is not None:
            # A full pipe whose reader is busy elsewhere: the write completes
            # only once the test's gate opens.
            await self._process.stdin_send_gate.wait()
        if self._process.stdin_send_blocks:
            # A pipe whose reader stopped reading: the write never completes.
            await anyio.sleep_forever()
        if self._process.stdin_send_error is not None:
            raise self._process.stdin_send_error
        if self._process.returncode is not None:
            # What the asyncio backend surfaces when writing to a dead child's pipe.
            raise ConnectionResetError("Connection lost")
        self._process.written.append(data)

    async def aclose(self) -> None:
        self._process.stdin_closed.set()
        if self._process.on_stdin_close is not None:
            self._process.on_stdin_close()
        if self._process.stdin_aclose_error is not None:
            raise self._process.stdin_aclose_error


class _FakeStdout:
    """The fake process's stdout: delegates to the in-memory stream, optionally
    surfacing the abrupt-death or close-time errors a real pipe can."""

    def __init__(
        self,
        inner: MemoryObjectReceiveStream[bytes],
        *,
        eof_error: Exception | None = None,
        aclose_error: Exception | None = None,
        on_receive: Callable[[], None],
    ) -> None:
        self._inner = inner
        self._eof_error = eof_error
        self._aclose_error = aclose_error
        self._on_receive = on_receive

    async def receive(self) -> bytes:
        try:
            chunk = await self._inner.receive()
        except anyio.EndOfStream:
            if self._eof_error is not None:
                # A hard-killed pipe surfaces a reset, not EOF, on the proactor loop.
                raise self._eof_error from None
            raise
        self._on_receive()
        return chunk

    async def aclose(self) -> None:
        await self._inner.aclose()
        if self._aclose_error is not None:
            raise self._aclose_error
        # Real async closes yield; keeps the fake honest and shutdown scheduling realistic.
        await anyio.lowlevel.checkpoint()


class FakeProcess:
    """In-memory stand-in for the spawned server process: `feed`/`close_stdout` drive its
    stdout, `written` records client writes, `exit` and the error knobs replay death and
    pipe failure modes."""

    def __init__(
        self,
        on_stdin_close: Callable[[], None] | None = None,
        stdin_aclose_error: Exception | None = None,
        stdin_send_error: Exception | None = None,
        stdin_send_blocks: bool = False,
        stdin_send_gate: anyio.Event | None = None,
        stdout_eof_error: Exception | None = None,
        stdout_aclose_error: Exception | None = None,
        on_stdout_receive: Callable[[], None] | None = None,
    ) -> None:
        self._stdout_send, stdout_receive = anyio.create_memory_object_stream[bytes](math.inf)
        self.stdout = _FakeStdout(
            stdout_receive,
            eof_error=stdout_eof_error,
            aclose_error=stdout_aclose_error,
            on_receive=self._dispatch_stdout_receive,
        )
        self.pid = 424242
        self.written: list[bytes] = []
        self.stdin_closed = anyio.Event()
        self.returncode: int | None = None
        self.on_stdin_close = on_stdin_close
        self.stdin_aclose_error = stdin_aclose_error
        self.stdin_send_error = stdin_send_error
        self.stdin_send_blocks = stdin_send_blocks
        self.stdin_send_gate = stdin_send_gate
        self.on_stdout_receive = on_stdout_receive
        self.stdin = _FakeStdin(self)

    def _dispatch_stdout_receive(self) -> None:
        # Late-bound so a test can assign `on_stdout_receive` after construction.
        if self.on_stdout_receive is not None:
            self.on_stdout_receive()

    async def feed(self, data: bytes) -> None:
        """Make `data` readable on the fake process's stdout."""
        await self._stdout_send.send(data)

    def close_stdout(self) -> None:
        """End the fake process's stdout, as the kernel does when it dies."""
        self._stdout_send.close()

    def exit(self, code: int = 0) -> None:
        """Die: set the exit code and EOF stdout, as the kernel does."""
        self.returncode = code
        self.close_stdout()

    def pending_stdout_chunks(self) -> int:
        """How many fed chunks the client has not yet pulled off the fake stdout."""
        return self._stdout_send.statistics().current_buffer_used


def install_fake_process(
    monkeypatch: pytest.MonkeyPatch, process: FakeProcess, *, grace_period: float | None = 0.2
) -> list[FakeProcess]:
    """Route stdio_client's spawn and terminate seams to `process`; returns the list of
    processes the (fake) tree termination was invoked on. `grace_period=None` keeps the
    production stdin-close grace (affordable only on a virtual clock)."""
    terminated: list[FakeProcess] = []

    async def fake_spawn(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: TextIO = sys.stderr,
        cwd: Path | str | None = None,
    ) -> FakeProcess:
        return process

    async def fake_terminate_tree(proc: FakeProcess) -> None:
        terminated.append(proc)
        proc.exit(-15)

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", fake_spawn)
    monkeypatch.setattr(stdio, "_terminate_process_tree", fake_terminate_tree)
    if grace_period is not None:
        monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", grace_period)
    return terminated


FAKE_PARAMS = StdioServerParameters(command="fake-server")


def _line(message: JSONRPCMessage) -> bytes:
    """The wire form of `message`: one JSON document on its own line."""
    return (message.model_dump_json(by_alias=True, exclude_unset=True) + "\n").encode()


async def _next_message(read_stream: ReadStream[SessionMessage | Exception]) -> JSONRPCMessage:
    received = await read_stream.receive()
    assert isinstance(received, SessionMessage)
    return received.message


@pytest.mark.anyio
async def test_messages_split_and_packed_across_chunks_are_reframed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Framing survives arbitrary chunk boundaries: split, packed, and CRLF-terminated
    messages are each delivered exactly once, and a trailing line without a newline is
    not delivered."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    ping2 = JSONRPCRequest(jsonrpc="2.0", id=2, method="ping")
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (read_stream, _):
            # First message split mid-bytes; its tail packed with the second, a
            # CRLF-framed third (the SDK's own server emits \r\n on Windows; jiter
            # treats the \r as JSON whitespace), and a partial fourth.
            wire = _line(ping)
            crlf_wire = ping2.model_dump_json(by_alias=True, exclude_unset=True).encode() + b"\r\n"
            await process.feed(wire[:7])
            await process.feed(wire[7:] + _line(pong) + crlf_wire + b'{"jsonrpc": "2.0", "id": 99')

            assert await _next_message(read_stream) == ping
            assert await _next_message(read_stream) == pong
            assert await _next_message(read_stream) == ping2

            # The partial trailing message is dropped at EOF, not delivered broken.
            # (no branch: coverage mis-traces the exit arc of a `with` whose body
            # raises inside a nested async context.)
            with pytest.raises(anyio.EndOfStream):  # pragma: no branch
                process.close_stdout()
                await read_stream.receive()


@pytest.mark.anyio
async def test_each_outgoing_message_is_written_as_exactly_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Client -> server framing: every sent message reaches the server's stdin as
    exactly one newline-terminated JSON document."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (_, write_stream):
            await write_stream.send(SessionMessage(ping))
            await write_stream.send(SessionMessage(pong))
            # The zero-buffer handoff resumes this task before the writer has
            # necessarily written; once all tasks block again, both writes have landed.
            await anyio.wait_all_tasks_blocked()
            assert process.written == [_line(ping), _line(pong)]


@pytest.mark.anyio
async def test_invalid_json_from_the_server_surfaces_as_an_in_stream_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A line that fails JSON-RPC validation is delivered as an Exception on the read
    stream, and the messages after it still come through."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (read_stream, _):
            await process.feed(b"not json\n" + _line(ping))

            error = await read_stream.receive()
            # The transport surfaces parse failures as the underlying validation error.
            assert isinstance(error, ValueError)
            assert await _next_message(read_stream) == ping


@pytest.mark.anyio
async def test_a_server_that_dies_before_responding_fails_initialize_with_connection_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server death (stdout EOF) is reported to the session as a closed connection
    instead of hanging the in-flight initialize."""
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))
    process.exit(1)

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with (
            stdio_client(FAKE_PARAMS) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            with pytest.raises(MCPError) as exc_info:
                await session.initialize()

            assert exc_info.value.error.code == CONNECTION_CLOSED
            assert exc_info.value.error.message == "Connection closed"


@pytest.mark.anyio
async def test_a_server_that_exits_on_stdin_close_is_never_terminated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing stdin (shutdown's first step) suffices for a well-behaved server: the
    escalation is never invoked. The fake's stdin also raises on close, which the
    shutdown must tolerate."""

    process = FakeProcess(
        on_stdin_close=lambda: process.exit(0),
        stdin_aclose_error=anyio.ClosedResourceError(),
    )
    terminated = install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            pass

    assert terminated == []
    assert process.stdin_closed.is_set()


def test_escalation_fires_once_and_only_after_the_grace_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server that ignores stdin closure is terminated at the grace deadline exactly:
    no earlier than the production `PROCESS_TERMINATION_TIMEOUT` on the runtime clock,
    and by the first `returncode` poll after it.

    The suite's only direct trio use: anyio's pytest plugin cannot hand the backend a
    clock, so the test calls `trio.run` itself with an autojumping `MockClock`. Every
    time primitive rides that one virtual clock, so the production grace elapses
    instantly and the bound can be two-sided (a wall-clock upper bound flakes under
    load). That virtual seconds match wall seconds is the runtime clock's contract,
    deliberately not re-tested here.
    """

    class ClockedFakeProcess(FakeProcess):
        """Records the virtual time of each death; only the (fake) tree termination
        calls `exit` here, so these are the escalation timestamps."""

        def __init__(self) -> None:
            super().__init__()
            self.exit_times: list[float] = []

        def exit(self, code: int = 0) -> None:
            self.exit_times.append(trio.current_time())
            super().exit(code)

    process = ClockedFakeProcess()
    terminated = install_fake_process(monkeypatch, process, grace_period=None)

    async def run_client() -> float:
        with anyio.fail_after(stdio.PROCESS_TERMINATION_TIMEOUT + 5):  # virtual seconds
            async with stdio_client(FAKE_PARAMS):
                # Evaluated just before the context exits: the moment cleanup begins.
                return trio.current_time()

    cleanup_started = trio.run(run_client, clock=trio.testing.MockClock(autojump_threshold=0))

    assert terminated == [process]
    virtual_elapsed = process.exit_times[0] - cleanup_started
    # Two-sided: never before the grace deadline, and within one poll interval past it
    # (shutdown's writer-flush poll); the epsilon absorbs virtual-sleep float drift.
    assert (
        stdio.PROCESS_TERMINATION_TIMEOUT
        <= virtual_elapsed
        <= stdio.PROCESS_TERMINATION_TIMEOUT + _EXIT_POLL_INTERVAL + 1e-9
    ), virtual_elapsed


def test_a_server_dying_in_the_final_poll_interval_is_not_escalated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server that exits during the very poll interval the grace deadline cuts
    short is dead, not hung: the timed-out grace wait must re-check `returncode`
    before deciding to escalate, so this server is never terminated.

    Runs on trio's MockClock (see the escalation-bound test above). The grace is
    set to end mid-interval (0.105 with 0.01 polls) and the fake dies at 0.102
    after its stdin closes, strictly between the last in-window poll (0.10) and
    the deadline (0.105), so no two timers collide."""
    process = FakeProcess()
    terminated = install_fake_process(monkeypatch, process, grace_period=0.105)

    async def run_client() -> None:
        with anyio.fail_after(5):  # virtual seconds
            async with anyio.create_task_group() as tg:

                async def die_late() -> None:
                    await anyio.sleep(0.102)
                    process.exit(0)

                # The grace wait starts when stdin closes; anchor the death there.
                process.on_stdin_close = lambda: tg.start_soon(die_late)
                # no branch: the tracer drops this nested async-with's arcs under
                # trio's MockClock even though the body runs.
                async with stdio_client(FAKE_PARAMS):  # pragma: no branch
                    pass

    trio.run(run_client, clock=trio.testing.MockClock(autojump_threshold=0))

    assert terminated == []
    assert process.returncode == 0


@pytest.mark.anyio
async def test_cancelling_the_client_still_runs_the_full_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation (a client timeout, app shutdown) must not skip the shutdown
    sequence: stdin is still closed and a server ignoring it is still terminated.
    Without the shielded shutdown this leaks the process and can deadlock."""
    process = FakeProcess()
    terminated = install_fake_process(monkeypatch, process, grace_period=0.05)
    entered = anyio.Event()
    # Cancel a scope owned by the client's task, not the test's task group: a host
    # self-cancel is delivered by throwing through this test function's suspended
    # frames, and Python 3.11's tracer loses coverage events after such a throw()
    # traversal (python/cpython#106749).
    cancel_scope = anyio.CancelScope()

    async def run_client_until_cancelled() -> None:
        with cancel_scope:
            async with stdio_client(FAKE_PARAMS):
                entered.set()
                await anyio.sleep_forever()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(run_client_until_cancelled)
            await entered.wait()
            cancel_scope.cancel()

    assert process.stdin_closed.is_set()
    assert terminated == [process]


@pytest.mark.anyio
async def test_writing_after_the_server_dies_reports_clean_closure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A send racing the server's death must not surface a raw backend exception
    (ConnectionResetError in an exception group) out of the context manager; the
    transport still shuts down cleanly."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (_, write_stream):
            process.exit(1)
            # The fake's stdin now raises ConnectionResetError, as a dead child's pipe does.
            await write_stream.send(SessionMessage(ping))

    assert process.written == []


@pytest.mark.anyio
async def test_exiting_with_an_unconsumed_server_message_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exiting while a server message is still undelivered must be a clean exit:
    shutdown closes the read stream under the blocked reader task, and that closure
    must not escape the caller as a BrokenResourceError in an exception group."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            # Feed a message and never receive it: the reader parses it and blocks
            # delivering into the zero-buffer read stream until shutdown breaks the send.
            await process.feed(_line(ping))
            # Wait until the reader task is genuinely parked on its blocked send
            # before shutdown closes the stream out from under it.
            await anyio.wait_all_tasks_blocked()


@pytest.mark.anyio
async def test_spawn_failure_propagates_the_error_and_leaks_no_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the spawn itself fails, the OSError reaches the caller and the transport's
    internal streams are all closed (an unclosed stream would fail the test through
    its GC-time ResourceWarning under filterwarnings=error)."""

    async def failing_spawn(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: TextIO = sys.stderr,
        cwd: Path | str | None = None,
    ) -> FakeProcess:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", failing_spawn)

    with pytest.raises(OSError) as exc_info:
        async with stdio_client(FAKE_PARAMS):
            pass  # pragma: no cover

    assert exc_info.value.errno == errno.EACCES
    # Drop the ExceptionInfo before collecting: its traceback references the suspended
    # stdio_client frame, which would keep leaked streams alive across the collect.
    del exc_info
    gc.collect()


@pytest.mark.anyio
async def test_a_command_that_cannot_be_execed_raises_enoent() -> None:
    """A command that cannot be exec'd raises OSError(ENOENT) out of stdio_client."""
    server_params = StdioServerParameters(
        command="/path/to/nonexistent/command",
        args=["--help"],
    )

    with pytest.raises(OSError) as exc_info:
        async with stdio_client(server_params):
            pass  # pragma: no cover

    assert exc_info.value.errno == errno.ENOENT


@pytest.mark.anyio
async def test_cancellation_during_spawn_leaks_no_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller timeout firing while the spawn is still in flight (interpreter cold
    start) must not leak the transport's internal streams: an unclosed stream would
    fail the test through its GC-time ResourceWarning under filterwarnings=error."""
    spawn_started = anyio.Event()

    async def hanging_spawn(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: TextIO = sys.stderr,
        cwd: Path | str | None = None,
    ) -> FakeProcess:
        spawn_started.set()
        await anyio.sleep_forever()
        raise NotImplementedError("unreachable: the spawn is cancelled while parked")

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", hanging_spawn)

    # Cancel a scope owned by the client's task, not the test's task group: a host
    # self-cancel is delivered by throwing through this test function's suspended
    # frames, and Python 3.11's tracer loses coverage events after such a throw()
    # traversal (python/cpython#106749).
    cancel_scope = anyio.CancelScope()

    async def run_client() -> None:
        with cancel_scope:
            async with stdio_client(FAKE_PARAMS):
                pass  # pragma: no cover

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(run_client)
            await spawn_started.wait()
            cancel_scope.cancel()

    gc.collect()


@pytest.mark.anyio
async def test_a_non_oserror_spawn_failure_propagates_and_leaks_no_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spawning can fail with more than OSError (e.g. ValueError for a NUL byte in
    the command); the error reaches the caller and the transport's internal streams
    are still all closed (checked through GC-time ResourceWarnings, as above)."""

    async def failing_spawn(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: TextIO = sys.stderr,
        cwd: Path | str | None = None,
    ) -> FakeProcess:
        raise ValueError("embedded null byte")

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", failing_spawn)

    with pytest.raises(ValueError, match="embedded null byte"):
        async with stdio_client(FAKE_PARAMS):
            pass  # pragma: no cover

    gc.collect()


@pytest.mark.anyio
async def test_a_message_sent_just_before_exit_is_flushed_to_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """A message the transport accepted must reach the server even when the caller
    exits immediately after sending it. Once the writer is parked waiting, a send is
    a pure handoff that returns before the write lands, so the second message here is
    the one shutdown must let the writer flush before closing the server's stdin."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))

    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (_, write_stream):
            await write_stream.send(SessionMessage(ping))
            await write_stream.send(SessionMessage(pong))

    assert process.written == [_line(ping), _line(pong)]


@pytest.mark.anyio
async def test_a_failed_write_to_a_live_server_closes_the_read_stream_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a write fails but the server is still alive (stdout never EOFs), the
    transport must end the read stream so a session maps the loss to CONNECTION_CLOSED
    instead of waiting forever. EIO pins that plain OSError, not just ConnectionError,
    is handled.

    Steps:
    1. A send fails with EIO while the server is alive; the read stream ends.
    2. Output the server produces afterwards is still drained, so it cannot wedge
       on a full pipe.
    """
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    process = FakeProcess(
        on_stdin_close=lambda: process.exit(0),
        stdin_send_error=OSError(errno.EIO, "I/O error"),
    )
    terminated = install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (read_stream, write_stream):
            await write_stream.send(SessionMessage(ping))

            with pytest.raises(anyio.EndOfStream):
                await read_stream.receive()

            await process.feed(_line(pong))
            await anyio.wait_all_tasks_blocked()
            assert process.pending_stdout_chunks() == 0

    assert process.written == []
    assert terminated == []


@pytest.mark.anyio
async def test_exit_completes_when_a_write_is_wedged_in_a_pipe_no_one_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exiting must stay bounded even when the writer task is parked in a write that
    can never complete (a kill-surviving descendant holds the read end without
    reading): the flush window expires and the post-shutdown cancellation unparks the
    writer."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    process = FakeProcess(on_stdin_close=lambda: process.exit(0), stdin_send_blocks=True)
    terminated = install_fake_process(monkeypatch, process)
    monkeypatch.setattr(stdio, "_WRITER_FLUSH_TIMEOUT", 0.05)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (_, write_stream):
            await write_stream.send(SessionMessage(ping))
            # Wait until the writer task is genuinely parked inside the wedged send.
            await anyio.wait_all_tasks_blocked()

    assert process.written == []
    assert terminated == []
    assert process.stdin_closed.is_set()


@pytest.mark.anyio
async def test_undelivered_server_output_is_drained_at_shutdown_so_the_server_can_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output the caller never received is consumed during the stdin-close grace
    period: a real server flushing its remaining output on the way out would otherwise
    block on a full pipe, never reach its stdin read, and be killed despite being
    well-behaved. The fake ignores stdin closure (so it is ultimately terminated);
    the pin is that its backlog was drained during the grace window."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    process = FakeProcess()
    terminated = install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            # Three separate chunks: the reader parks delivering the first; the other
            # two sit unconsumed in the pipe when shutdown begins.
            await process.feed(_line(ping))
            await process.feed(_line(pong))
            await process.feed(_line(ping))
            await anyio.wait_all_tasks_blocked()
            assert process.pending_stdout_chunks() == 2

    assert terminated == [process]
    assert process.pending_stdout_chunks() == 0


@pytest.mark.anyio
async def test_shutdown_drains_stdout_first_so_a_wedged_writers_flush_can_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server wedged writing its stdout cannot get to reading its stdin, so a client
    write can sit in a full pipe. Shutdown must unblock the reader's drain before
    waiting out the writer flush: the drain is what unwedges the server and lets the
    flush complete."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})

    received = 0
    stdin_gate = anyio.Event()

    def unwedge_once_drained() -> None:
        # Accept the client's write only once all three output chunks are consumed,
        # like a real server whose blocked stdout write gates its stdin read.
        nonlocal received
        received += 1
        if received == 3:
            stdin_gate.set()

    process = FakeProcess(
        on_stdin_close=lambda: process.exit(0),
        stdin_send_gate=stdin_gate,
        on_stdout_receive=unwedge_once_drained,
    )
    terminated = install_fake_process(monkeypatch, process)
    # A flush wait that never gets unwedged would outlast the whole test budget.
    monkeypatch.setattr(stdio, "_WRITER_FLUSH_TIMEOUT", 30.0)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (_read_stream, write_stream):
            # The reader parks delivering a message nobody receives, with more
            # chunks backed up behind it; the writer parks in the gated send.
            await process.feed(_line(ping))
            await process.feed(_line(pong))
            await process.feed(_line(ping))
            await write_stream.send(SessionMessage(ping))
            await anyio.wait_all_tasks_blocked()

    assert terminated == []
    assert len(process.written) == 1
    assert process.pending_stdout_chunks() == 0


@pytest.mark.anyio
async def test_cancellation_with_undelivered_backlog_still_drains_and_spares_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation must not skip the shutdown drain: a well-behaved server that
    can only exit once its remaining output is consumed (a real one blocks on a
    full stdout pipe) still exits within the grace period and is never terminated."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    pong = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    process = FakeProcess()
    terminated = install_fake_process(monkeypatch, process)

    def exit_when_flushed() -> None:
        # The fake exits only once its stdin has closed AND its output backlog
        # has been consumed, like a real server wedged writing its stdout.
        if process.stdin_closed.is_set() and process.pending_stdout_chunks() == 0:
            process.exit(0)

    process.on_stdin_close = exit_when_flushed
    process.on_stdout_receive = exit_when_flushed

    entered = anyio.Event()
    # Cancel a scope owned by the client's task, not the test's task group (see
    # test_cancelling_the_client_still_runs_the_full_shutdown).
    cancel_scope = anyio.CancelScope()

    async def run_client_until_cancelled() -> None:
        with cancel_scope:
            async with stdio_client(FAKE_PARAMS):
                await process.feed(_line(ping))
                await process.feed(_line(pong))
                await process.feed(_line(ping))
                entered.set()
                await anyio.sleep_forever()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(run_client_until_cancelled)
            await entered.wait()
            cancel_scope.cancel()

    assert process.pending_stdout_chunks() == 0
    assert terminated == []


@pytest.mark.anyio
async def test_invalid_utf8_flushed_by_a_dying_server_does_not_break_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shutdown drain consumes raw bytes: a server flushing non-UTF-8 output
    (a crash dump, say) on its way out must not abort the drain or surface a
    UnicodeDecodeError out of the context manager."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    process = FakeProcess(on_stdin_close=lambda: process.exit(0))
    terminated = install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            # Park the reader delivering a message nobody receives, then queue
            # bytes that are not valid UTF-8 behind it.
            await process.feed(_line(ping))
            await anyio.wait_all_tasks_blocked()
            await process.feed(b"\xff\xfe not utf-8\n")

    assert terminated == []
    assert process.pending_stdout_chunks() == 0


@pytest.mark.anyio
async def test_a_kill_racing_a_pending_stdout_read_is_swallowed_during_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A hard kill during a pending stdout read surfaces ConnectionResetError from the
    read on the proactor backend; it must not escape the context manager, and being
    expected teardown noise, it is not logged as an error either."""
    process = FakeProcess(stdout_eof_error=ConnectionResetError("read torn down by kill"))
    terminated = install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            pass  # the fake ignores stdin closure, so shutdown must escalate

    assert terminated == [process]
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.anyio
async def test_a_mid_session_stdout_failure_is_logged_and_surfaces_as_clean_closure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stdout read failure in the middle of a session (not during shutdown) ends
    the read stream cleanly, with no raw exception out of the context manager, and
    leaves an error log identifying the failure, unlike the silent shutdown case."""
    process = FakeProcess(
        on_stdin_close=lambda: process.exit(0),
        stdout_eof_error=ConnectionResetError("pipe failed mid-session"),
    )
    install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS) as (read_stream, _):
            process.exit(1)
            # (no branch: coverage mis-traces the exit arc of a `with` whose body
            # raises inside a nested async context.)
            with pytest.raises(anyio.EndOfStream):  # pragma: no branch
                await read_stream.receive()

    assert "stdout failed mid-session" in caplog.text


@pytest.mark.anyio
async def test_a_failing_stdout_close_still_closes_the_transport_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    """A close-time error on the process's stdout (a contended pipe handle on the
    Windows fallback) must not abort the rest of the shutdown: the context exits
    cleanly and the internal streams are all closed (checked via GC-time
    ResourceWarnings)."""
    process = FakeProcess(
        on_stdin_close=lambda: process.exit(0),
        stdout_aclose_error=OSError(errno.EBADF, "Bad file descriptor"),
    )
    terminated = install_fake_process(monkeypatch, process)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            pass

    assert terminated == []
    gc.collect()


@pytest.mark.anyio
async def test_a_process_surviving_the_kill_escalation_is_logged_and_abandoned(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the process is still alive after the whole escalation (D-state, an
    unsignalable survivor), shutdown still completes, bounded, and leaves a warning
    instead of silently leaking a live process."""
    process = FakeProcess()  # ignores stdin closure and survives "termination"
    install_fake_process(monkeypatch, process, grace_period=0.05)

    stubborn: list[FakeProcess] = []

    async def stubborn_terminate(proc: FakeProcess) -> None:
        stubborn.append(proc)  # the kill has no effect

    monkeypatch.setattr(stdio, "_terminate_process_tree", stubborn_terminate)
    monkeypatch.setattr(stdio, "_KILL_REAP_TIMEOUT", 0.05)

    with anyio.fail_after(5):
        async with stdio_client(FAKE_PARAMS):
            pass

    assert stubborn == [process]
    assert process.returncode is None
    assert "still alive after the kill escalation" in caplog.text
    # The fake "survived", so nothing ever EOF'd its stdout pipe; release it here
    # or its GC-time ResourceWarning would fail a later test.
    process.close_stdout()


# ---------------------------------------------------------------------------
# POSIX tree-termination policy, tested through the sanctioned killpg seam
# ---------------------------------------------------------------------------
#
# `mcp.os.posix.utilities` is coverage-omitted and the sanctioned place to monkeypatch
# OS calls. These pin the EPERM policy without a foreign-euid process: macOS killpg
# raises EPERM when *any* group member cannot be signalled, even if others were.


class _StubPosixProcess:
    """The two attributes `terminate_posix_process_tree` touches: the pgid source
    and the reap-progress probe."""

    pid = 54321
    returncode: int | None = None


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX killpg semantics")
# lax no cover: Windows CI jobs enforce 100% coverage per job and skip this test.
async def test_an_eperm_group_that_dies_during_the_grace_period_is_not_sigkilled(  # pragma: lax no cover
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EPERM from the SIGTERM killpg no longer short-circuits termination: the grace
    wait still runs, and a group observed to be gone during it is never SIGKILLed."""
    calls: list[tuple[int, int]] = []
    probes = 0

    def fake_killpg(pgid: int, sig: int) -> None:
        nonlocal probes
        calls.append((pgid, sig))
        if sig == signal.SIGTERM:
            raise PermissionError("one group member has a foreign euid")
        if sig == 0:
            probes += 1
            if probes == 1:
                raise PermissionError("survivors we may not signal")
            raise ProcessLookupError("group is gone")
        raise NotImplementedError("no other signal should be sent")

    monkeypatch.setattr(posix_utilities.os, "killpg", fake_killpg)
    stub = _StubPosixProcess()

    with anyio.fail_after(5):
        await terminate_posix_process_tree(cast(anyio.abc.Process, stub))

    assert calls == [(stub.pid, signal.SIGTERM), (stub.pid, 0), (stub.pid, 0)]


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX killpg semantics")
# lax no cover: same Windows-runner coverage reason as above.
async def test_an_eperm_group_that_outlives_the_grace_period_is_still_sigkilled(  # pragma: lax no cover
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when every probe reports EPERM, the SIGKILL escalation still fires after
    the grace period (and its own EPERM is tolerated). Pre-fix, EPERM at SIGTERM
    abandoned the group escalation for a leader-only kill, leaking every other group
    member. The tiny timeout is the time-based grace period under test."""
    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))
        if sig in (signal.SIGTERM, 0, signal.SIGKILL):
            raise PermissionError("a foreign-euid member never goes away")
        raise NotImplementedError("no other signal should be sent")

    monkeypatch.setattr(posix_utilities.os, "killpg", fake_killpg)
    stub = _StubPosixProcess()

    with anyio.fail_after(5):
        await terminate_posix_process_tree(cast(anyio.abc.Process, stub), timeout_seconds=0.05)

    assert calls[0] == (stub.pid, signal.SIGTERM)
    assert calls[-1] == (stub.pid, signal.SIGKILL)
    assert set(calls[1:-1]) == {(stub.pid, 0)}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio"])
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX killpg semantics")
# lax no cover: same Windows-runner coverage reason as above.
async def test_the_grace_wait_reads_returncode_so_trio_can_reap_the_leaders_zombie(  # pragma: lax no cover
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wait between SIGTERM and SIGKILL reads `process.returncode` while it polls:
    on trio that property calls `Popen.poll()`, whose reap stops the leader's zombie
    from keeping the group alive for the full timeout (see terminate_posix_process_tree).
    Regression pin for the read itself, on both backends; the reaping side effect is
    trio's documented behaviour, deliberately not re-tested here."""

    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        # SIGTERM is accepted and every liveness probe reports survivors, so the
        # grace wait runs to its (tiny) timeout and the SIGKILL escalation fires.
        calls.append((pgid, sig))

    class _ReadCountingProcess:
        """A live-forever leader whose `returncode` property counts its reads."""

        pid = 54321

        def __init__(self) -> None:
            self.returncode_reads = 0

        @property
        def returncode(self) -> int | None:
            self.returncode_reads += 1
            return None

    monkeypatch.setattr(posix_utilities.os, "killpg", fake_killpg)
    stub = _ReadCountingProcess()

    with anyio.fail_after(5):
        await terminate_posix_process_tree(cast(anyio.abc.Process, stub), timeout_seconds=0.05)

    # The wait ran to its deadline (the escalation fired)...
    assert calls[0] == (stub.pid, signal.SIGTERM)
    assert calls[-1] == (stub.pid, signal.SIGKILL)
    # ...and `returncode` was read while it polled, the read that reaps on trio.
    assert stub.returncode_reads >= 1


# ---------------------------------------------------------------------------
# Real-process tests: the OS facts no fake can certify
# ---------------------------------------------------------------------------
#
# These pin kernel behaviour (process-group kill semantics, SIGKILL delivery) via a
# socket liveness probe, no sleeps or polls: `accept()` blocks until the subprocess
# connects, proving it runs (and its pre-connect setup ran); after cleanup, `receive(1)`
# raises EndOfStream (FIN) or BrokenResourceError (RST, typical of SIGKILL and Windows
# job termination) because the kernel closes a dead process's file descriptors.


def _connect_back_script(port: int) -> str:
    """Return a ``python -c`` liveness-probe body: connect to `port`, send `b'alive'`,
    block forever."""
    return (
        f"import socket, time\n"
        f"s = socket.create_connection(('127.0.0.1', {port}))\n"
        f"s.sendall(b'alive')\n"
        f"time.sleep(3600)\n"
    )


async def _open_liveness_listener() -> tuple[anyio.abc.SocketListener, int]:
    """Open a TCP listener on localhost and return it along with its port."""
    multi = await anyio.create_tcp_listener(local_host="127.0.0.1")
    sock = multi.listeners[0]
    assert isinstance(sock, anyio.abc.SocketListener)
    addr = sock.extra(anyio.abc.SocketAttribute.local_address)
    # IPv4 local_address is (host: str, port: int)
    assert isinstance(addr, tuple) and len(addr) >= 2 and isinstance(addr[1], int)
    return sock, addr[1]


async def _accept_alive(sock: anyio.abc.SocketListener) -> anyio.abc.SocketStream:
    """Accept one connection and assert the peer sent ``b'alive'``; blocks until a
    subprocess connects (the outer test bounds this with ``anyio.fail_after``)."""
    stream = await sock.accept()
    msg = await stream.receive(5)
    assert msg == b"alive", f"expected b'alive', got {msg!r}"
    return stream


async def _assert_stream_closed(stream: anyio.abc.SocketStream) -> None:
    """Assert the peer holding the other end of `stream` has terminated."""
    with anyio.fail_after(5.0), pytest.raises((anyio.EndOfStream, anyio.BrokenResourceError)):
        await stream.receive(1)


# lax no cover: only called by win32-skipped tests; Windows CI jobs enforce 100%
# coverage per job, where these helpers never execute.
async def _wait_until_exited(proc: anyio.abc.Process) -> None:  # pragma: lax no cover
    """Poll `returncode` until the process itself dies. Not `proc.wait()`: on asyncio
    that also waits for the pipes to close, conflating process death with pipe state."""
    while proc.returncode is None:
        await anyio.sleep(0.01)


async def _reap(proc: anyio.abc.Process) -> None:  # pragma: lax no cover
    """Reap an already-killed process and release its pipe transports: draining stdout
    to EOF lets the asyncio pipe transport observe the closure instead of warning at
    GC. The bound swallows a hung cleanup on purpose; reaping is just a safety net."""
    with anyio.move_on_after(5.0):
        await proc.wait()
        assert proc.stdin is not None
        assert proc.stdout is not None
        await proc.stdin.aclose()
        with suppress(anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError):
            await proc.stdout.receive(65536)
        await proc.stdout.aclose()


def _record_spawned_processes(monkeypatch: pytest.MonkeyPatch) -> list[anyio.abc.Process | FallbackProcess]:
    """Record every process `stdio_client` spawns (the real spawn still runs), so a
    test can inspect it afterwards and tear its process group down on failure."""
    spawned: list[anyio.abc.Process | FallbackProcess] = []

    async def recording_spawn(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: TextIO = sys.stderr,
        cwd: Path | str | None = None,
    ) -> anyio.abc.Process | FallbackProcess:
        process = await _create_platform_compatible_process(command, args, env, errlog, cwd)
        spawned.append(process)
        return process

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", recording_spawn)
    return spawned


# lax no cover: registered on every platform but a no-op on Windows, whose runners
# enforce 100% coverage per job.
def _kill_spawn_groups(spawned: list[anyio.abc.Process | FallbackProcess]) -> None:  # pragma: lax no cover
    """Failure-path safety net: SIGKILL each spawn-time process group so a test failing
    mid-body cannot orphan its sleep-forever descendants. A no-op when the test passed,
    and on Windows (no process group to signal; the Job Object covers strays)."""
    if sys.platform == "win32":
        return
    for process in spawned:
        # macOS killpg raises EPERM for a group holding only unreaped zombies.
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)


@pytest.mark.anyio
async def test_exiting_the_context_terminates_the_entire_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exiting `stdio_client` kills the server's whole process tree: a parent that
    exits instantly on SIGTERM (so the group must outlive its leader), a child, and a
    grandchild, each death observed through its liveness socket closing. The escalation
    timing is pinned in process by test_escalation_fires_once_and_only_after_the_grace_period;
    the production grace constant's value is deliberately unpinned."""
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 0.2)
    spawned = _record_spawned_processes(monkeypatch)

    async with AsyncExitStack() as stack:
        stack.callback(_kill_spawn_groups, spawned)
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        grandchild = _connect_back_script(port)
        child = (
            f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
            + _connect_back_script(port)
        )
        # The parent exits immediately on SIGTERM and never reads stdin, so cleanup
        # must escalate, and the group kill must work even as its leader dies first.
        parent = (
            f"import signal, subprocess, sys, time\n"
            f"signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n" + _connect_back_script(port)
        )
        server_params = StdioServerParameters(command=sys.executable, args=["-c", parent])

        # The bound covers three Python interpreter cold starts on a loaded runner;
        # a healthy run takes well under a second.
        with anyio.fail_after(15.0):
            async with stdio_client(server_params):
                streams = [await _accept_alive(sock) for _ in range(3)]
                for stream in streams:
                    stack.push_async_callback(stream.aclose)

        for stream in streams:
            await _assert_stream_closed(stream)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics")
# lax no cover: Windows CI jobs enforce 100% coverage per job and skip this test.
async def test_tree_kill_reaches_children_after_the_leader_has_already_exited() -> None:  # pragma: lax no cover
    """Killing the tree of a process that has already exited must still reach its
    surviving children: the process group outlives its leader, and the group ID is
    the leader's pid by construction (start_new_session), not something to look up
    from the (reaped) leader."""
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        child = _connect_back_script(port)
        # The parent spawns the child and exits immediately: the group leader is dead
        # (and reaped) by the time the tree is terminated.
        parent = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n"
        proc = await _create_platform_compatible_process(sys.executable, ["-c", parent])
        assert isinstance(proc, anyio.abc.Process)
        stack.callback(_kill_spawn_groups, [proc])
        stack.push_async_callback(_reap, proc)

        # Two interpreter cold starts on a loaded runner; healthy runs take ~0.2s.
        with anyio.fail_after(10.0):
            stream = await _accept_alive(sock)
            stack.push_async_callback(stream.aclose)
            # The child connecting proves the parent ran; wait for the leader itself
            # to be gone so the kill exercises the dead-leader path.
            await _wait_until_exited(proc)

        await _terminate_process_tree(proc)

        await _assert_stream_closed(stream)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics")
# lax no cover: same Windows-runner coverage reason as above.
async def test_terminating_an_already_exited_process_is_a_no_op() -> None:  # pragma: lax no cover
    """Once the whole group is gone, tree termination returns without error (and
    without falling back to signalling a reaped pid)."""
    proc = await _create_platform_compatible_process(sys.executable, ["-c", "pass"])
    assert isinstance(proc, anyio.abc.Process)

    # The bound covers one interpreter cold start on a loaded runner; a healthy run
    # takes well under a second.
    with anyio.fail_after(10.0):
        await _wait_until_exited(proc)
        await _terminate_process_tree(proc)
        await _reap(proc)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows signal handling is different")
# lax no cover: Windows CI jobs enforce 100% coverage per job and skip this test.
async def test_escalation_kills_a_process_that_ignores_sigterm(  # pragma: lax no cover
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup escalates past SIGTERM and kills a process that ignores it.

    The child installs SIG_IGN *before* connecting to the liveness socket, so the
    ignore is guaranteed in place; SIGKILL delivery is proven by the kernel closing
    the socket. The only test of the SIGTERM-then-SIGKILL escalation itself; the
    production constants' values are deliberately unpinned.
    """
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 0.2)
    monkeypatch.setattr(stdio, "FORCE_KILL_TIMEOUT", 0.2)
    spawned = _record_spawned_processes(monkeypatch)

    async with AsyncExitStack() as stack:
        stack.callback(_kill_spawn_groups, spawned)
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        script = "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" + _connect_back_script(port)
        server_params = StdioServerParameters(command=sys.executable, args=["-c", script])

        # The bound covers an interpreter cold start on a loaded runner plus the two
        # shortened escalation waits; a healthy run takes well under a second.
        with anyio.fail_after(15.0):
            async with stdio_client(server_params):
                stream = await _accept_alive(sock)
                stack.push_async_callback(stream.aclose)

        await _assert_stream_closed(stream)


@pytest.mark.anyio
@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="needs procfs to enumerate open file descriptors")
# lax no cover: Windows CI jobs enforce 100% coverage per job, have no procfs, and skip this.
async def test_a_graceful_exit_with_a_surviving_child_leaks_no_pipe_fds(  # pragma: lax no cover
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server may exit cleanly on stdin closure while leaving a child holding the
    inherited pipe ends (the POSIX policy: survivors are the server's business). The
    client must still release its own pipe fds and subprocess transport at shutdown
    (on asyncio nothing else ever closes them while the orphan holds the pipe) instead
    of leaking them for the orphan's lifetime."""
    spawned = _record_spawned_processes(monkeypatch)

    async with AsyncExitStack() as stack:
        stack.callback(_kill_spawn_groups, spawned)
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        child = _connect_back_script(port)
        # The server hands its inherited pipes to a child, then exits as soon as its
        # stdin closes: the well-behaved graceful path, so no kill ever happens.
        server = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\nsys.stdin.read()\n"
        server_params = StdioServerParameters(command=sys.executable, args=["-c", server])

        gc.collect()  # settle earlier garbage so its collection cannot close fds mid-test
        baseline = set(os.listdir("/proc/self/fd"))

        # Two interpreter cold starts on a loaded runner; healthy runs take ~0.3s.
        with anyio.fail_after(15.0):
            async with stdio_client(server_params):
                stream = await _accept_alive(sock)
            await stream.aclose()

        leader = spawned[0]
        assert isinstance(leader, anyio.abc.Process)
        # The graceful path: exited on stdin closure, no termination involved.
        assert leader.returncode == 0
        # Subset, not equality: other machinery may close fds, but never open new
        # ones; a leaked pipe fd would show up as an extra entry.
        assert set(os.listdir("/proc/self/fd")) <= baseline
