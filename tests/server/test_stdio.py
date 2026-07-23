import gc
import io
import os
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from io import TextIOWrapper

import anyio
import anyio.to_thread
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)
from typing_extensions import Buffer

from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage


@pytest.mark.anyio
async def test_stdio_server_round_trips_messages_over_injected_streams() -> None:
    """stdio_server frames JSON-RPC messages as one line each in both directions."""
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
        JSONRPCResponse(jsonrpc="2.0", id=2, result={}),
    ]

    for message in messages:
        stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    with anyio.fail_after(5):
        async with stdio_server(stdin=anyio.AsyncFile(stdin), stdout=anyio.AsyncFile(stdout)) as (
            read_stream,
            write_stream,
        ):
            async with read_stream:
                received_messages: list[JSONRPCMessage] = []
                for _ in range(2):
                    received = await read_stream.receive()
                    assert not isinstance(received, Exception)
                    received_messages.append(received.message)

            assert received_messages[0] == JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
            assert received_messages[1] == JSONRPCResponse(jsonrpc="2.0", id=2, result={})

            responses = [
                JSONRPCRequest(jsonrpc="2.0", id=3, method="ping"),
                JSONRPCResponse(jsonrpc="2.0", id=4, result={}),
            ]

            for response in responses:
                await write_stream.send(SessionMessage(response))
            await write_stream.aclose()

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    received_responses = [jsonrpc_message_adapter.validate_json(line.strip()) for line in output_lines]
    assert received_responses[0] == JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
    assert received_responses[1] == JSONRPCResponse(jsonrpc="2.0", id=4, result={})


@pytest.mark.anyio
async def test_stdio_server_invalid_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-UTF-8 stdin bytes surface as an in-stream exception without killing the stream."""
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = io.BytesIO(b"\xff\xfe\n" + valid.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")

    # stdio_server()'s default path wraps sys.stdin.buffer with errors='replace'.
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(raw_stdin, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    with anyio.fail_after(5):
        async with stdio_server() as (read_stream, write_stream):
            await write_stream.aclose()
            async with read_stream:  # pragma: no branch
                first = await read_stream.receive()
                assert isinstance(first, Exception)

                second = await read_stream.receive()
                assert isinstance(second, SessionMessage)
                assert second.message == valid


@contextmanager
def _pipe_planted_on_fd0(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, int]]:
    """Plants a fresh pipe on fd 0 and rebinds sys.stdin over it; yields (read_fd, write_fd).

    Close ownership: the caller closes the write end exactly once; the helper closes only what
    it created - a double close lands on a recycled fd and destroys whatever unrelated file now
    lives there (pytest's capture files). os.dup2 is captured up front to survive monkeypatching.
    """
    real_dup2 = os.dup2
    in_r, in_w = os.pipe()
    saved0 = os.dup(0)
    os.dup2(in_r, 0)
    # Created after the plant so its cached stream state describes the pipe.
    stdin_double = TextIOWrapper(open(0, "rb", closefd=False), encoding="utf-8")
    try:
        monkeypatch.setattr(sys, "stdin", stdin_double)
        yield in_r, in_w
    finally:
        stdin_double.close()
        real_dup2(saved0, 0)
        os.close(saved0)
        os.close(in_r)


@contextmanager
def _pipe_planted_on_fd1(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, int]]:
    """Like _pipe_planted_on_fd0 but plants fd 1 and rebinds sys.stdout; yields (read_fd, write_fd)."""
    real_dup2 = os.dup2
    out_r, out_w = os.pipe()
    saved1 = os.dup(1)
    os.dup2(out_w, 1)
    stdout_double = TextIOWrapper(open(1, "wb", closefd=False), encoding="utf-8")
    try:
        monkeypatch.setattr(sys, "stdout", stdout_double)
        yield out_r, out_w
    finally:
        stdout_double.close()
        real_dup2(saved1, 1)
        os.close(saved1)
        os.close(out_r)
        os.close(out_w)


@contextmanager
def _pipe_planted_on_fd2() -> Iterator[int]:
    """Like _pipe_planted_on_fd0 but plants fd 2 to observe the stdout diversion; yields the read end."""
    real_dup2 = os.dup2
    err_r, err_w = os.pipe()
    saved2 = os.dup(2)
    try:
        os.dup2(err_w, 2)
        yield err_r
    finally:
        real_dup2(saved2, 2)
        os.close(saved2)
        os.close(err_r)
        os.close(err_w)


def _frame(message: JSONRPCRequest | JSONRPCResponse) -> bytes:
    """One JSON-RPC message as the newline-terminated wire line the transport reads."""
    return (message.model_dump_json(by_alias=True, exclude_none=True) + "\n").encode()


async def _read_from(fd: int) -> bytes:
    """One os.read from fd, in a worker thread.

    A regression can leave the pipe empty; abandoning turns a read that would outlive
    fail_after on the loop thread into a red TimeoutError instead.
    """
    return await anyio.to_thread.run_sync(os.read, fd, 65536, abandon_on_cancel=True)


@pytest.mark.anyio
async def test_stdio_server_takes_stdin_off_the_descriptor_table_while_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the real process stdin, the transport claims the protocol pipe and releases it on exit.

    SDK-defined behavior: while serving, fd 0 is the null device, so an inheriting child
    cannot consume protocol bytes or, on Windows, hang at startup (CPython gh-78961).
    """
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w):
        out_r, out_w = os.pipe()
        stdout_double = TextIOWrapper(open(out_w, "wb", closefd=False), encoding="utf-8")
        try:
            monkeypatch.setattr(sys, "stdout", stdout_double)

            request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
            response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
            with anyio.fail_after(5):
                async with stdio_server() as (read_stream, write_stream):
                    async with read_stream:
                        # fd 0 is the null device: instant EOF instead of protocol bytes.
                        assert await anyio.to_thread.run_sync(os.read, 0, 1, abandon_on_cancel=True) == b""

                        os.write(in_w, _frame(request))
                        received = await read_stream.receive()
                        assert isinstance(received, SessionMessage)
                        assert received.message == request

                        await write_stream.send(SessionMessage(response))
                        line = await _read_from(out_r)
                        assert jsonrpc_message_adapter.validate_json(line.decode().strip()) == response

                        os.close(in_w)  # EOF lets the reader finish so the context can exit
                        await write_stream.aclose()

                # samestat is trivially-true for pipes on Windows; POSIX legs carry these assertions.
                assert os.path.sameopenfile(0, in_r)
        finally:
            stdout_double.close()
            os.close(out_r)
            os.close(out_w)


@pytest.mark.anyio
@pytest.mark.parametrize("failing_call", ["dup", "dup2"])
async def test_stdio_server_reads_stdin_in_place_when_descriptor_isolation_fails(
    failing_call: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A descriptor failure while claiming stdin degrades to reading sys.stdin in place.

    SDK-defined behavior: isolation is best-effort; when duplicating fd 0 or diverting
    it fails, the transport serves over the original stdin exactly as v1 did.
    """
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w):
        os.write(in_w, _frame(request))
        os.close(in_w)
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        if failing_call == "dup":

            def failing_dup_above_std(fd: int) -> int:
                raise OSError("injected descriptor failure")

            monkeypatch.setattr("mcp.server.stdio._dup_above_std", failing_dup_above_std)
        else:
            # Fires once at the divert, then passes through: pytest's capture
            # machinery also calls os.dup2 at phase transitions.
            real_dup2 = os.dup2
            armed = [True]

            def failing_dup2(fd: int, fd2: int, inheritable: bool = True) -> int:
                if armed[0]:
                    armed[0] = False
                    raise OSError("injected descriptor failure")
                return real_dup2(fd, fd2, inheritable)

            monkeypatch.setattr(os, "dup2", failing_dup2)

        with anyio.fail_after(5):
            async with stdio_server() as (read_stream, write_stream):  # pragma: no branch
                async with read_stream:  # pragma: no branch
                    # Isolation was skipped: fd 0 is still the protocol pipe.
                    assert os.path.sameopenfile(0, in_r)
                    received = await read_stream.receive()
                    assert isinstance(received, SessionMessage)
                    assert received.message == request
                    await write_stream.aclose()


@pytest.mark.anyio
async def test_stdio_server_exits_cleanly_when_the_stdin_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed fd 0 restore on exit is swallowed, not raised, and the fd stays claimed.

    SDK-defined behavior: the restore must never mask what ended the transport, and a
    still-diverted fd must refuse later transports rather than serve them the diversion.
    """
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    monkeypatch.setattr("mcp.server.stdio._claims", {})  # this test leaves fd 0 claimed
    with _pipe_planted_on_fd0(monkeypatch) as (_, in_w):
        os.write(in_w, _frame(request))
        os.close(in_w)
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        # The claim's dup2 (first call) succeeds; only the restore's (second) fails.
        real_dup2 = os.dup2
        dup2_calls: list[tuple[int, int]] = []

        def flaky_dup2(fd: int, fd2: int, inheritable: bool = True) -> int:
            dup2_calls.append((fd, fd2))
            if len(dup2_calls) == 2:
                raise OSError("injected restore failure")
            return real_dup2(fd, fd2, inheritable)

        monkeypatch.setattr(os, "dup2", flaky_dup2)

        with anyio.fail_after(5):
            async with stdio_server() as (read_stream, write_stream):  # pragma: no branch
                async with read_stream:  # pragma: no branch
                    received = await read_stream.receive()
                    assert isinstance(received, SessionMessage)
                    assert received.message == request
                    await write_stream.aclose()

        # Restore attempted (second dup2), failure swallowed, fd 0 left on the null device.
        assert dup2_calls[1] == (dup2_calls[1][0], 0)
        devnull_probe = os.open(os.devnull, os.O_RDONLY)
        try:
            assert os.path.sameopenfile(0, devnull_probe)
        finally:
            os.close(devnull_probe)

        # The still-diverted fd stays claimed: a later transport is refused,
        # not handed the null device as its wire.
        with pytest.raises(RuntimeError, match="already claimed fd 0"):
            async with stdio_server():
                pytest.fail("unreachable")  # pragma: no cover


@pytest.mark.anyio
async def test_stdio_server_takes_stdout_off_the_descriptor_table_while_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the real process stdout, the transport claims the wire and diverts fd 1 to stderr.

    SDK-defined behavior: stray writes to fd 1 land in the client's log, not the JSON-RPC stream.
    """
    response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    with _pipe_planted_on_fd1(monkeypatch) as (out_r, out_w), _pipe_planted_on_fd2() as err_r:
        with anyio.fail_after(5):
            async with stdio_server(stdin=anyio.AsyncFile(io.StringIO())) as (read_stream, write_stream):
                read_stream.close()
                os.write(1, b"stray child output\n")
                assert await _read_from(err_r) == b"stray child output\n"

                # The text layer writes os.linesep, hence CRLF on Windows.
                print("stray print", flush=True)
                assert await _read_from(err_r) == b"stray print" + os.linesep.encode()

                await write_stream.send(SessionMessage(response))
                line = await _read_from(out_r)
                assert jsonrpc_message_adapter.validate_json(line.decode().strip()) == response

                await write_stream.aclose()

        assert os.path.sameopenfile(1, out_w)


@pytest.mark.anyio
async def test_stdio_server_diverts_stdout_to_the_null_device_when_stderr_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When stderr cannot be duplicated, fd 1 is diverted to the null device instead.

    SDK-defined behavior: a process with unusable fd 2 still gets stdout claimed; the wire stays pure.
    """
    response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    with _pipe_planted_on_fd1(monkeypatch) as (out_r, out_w):
        # One-shot injector, as in the isolation-failure test.
        real_dup = os.dup
        armed = [True]

        def failing_dup(fd: int) -> int:
            if fd == 2 and armed[0]:
                armed[0] = False
                raise OSError("injected stderr failure")
            return real_dup(fd)

        monkeypatch.setattr(os, "dup", failing_dup)

        with anyio.fail_after(5):
            async with stdio_server(stdin=anyio.AsyncFile(io.StringIO())) as (read_stream, write_stream):
                read_stream.close()
                # The spent injector passes later duplications through untouched.
                os.close(os.dup(0))
                devnull_probe = os.open(os.devnull, os.O_WRONLY)
                try:
                    assert os.path.sameopenfile(1, devnull_probe)
                finally:
                    os.close(devnull_probe)

                os.write(1, b"discarded\n")
                await write_stream.send(SessionMessage(response))
                line = await _read_from(out_r)
                assert jsonrpc_message_adapter.validate_json(line.decode().strip()) == response
                await write_stream.aclose()

        assert os.path.sameopenfile(1, out_w)


@pytest.mark.anyio
async def test_a_second_stdio_server_on_the_same_process_streams_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent stdio_server() on already-claimed streams raises instead of contending."""
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w), _pipe_planted_on_fd1(monkeypatch) as (out_r, out_w):
        with anyio.fail_after(5):
            async with stdio_server() as (read_stream, write_stream):
                async with read_stream:  # pragma: no branch
                    with pytest.raises(RuntimeError, match="already claimed fd 0"):
                        async with stdio_server():
                            pytest.fail("unreachable")  # pragma: no cover

                    os.write(in_w, _frame(request))
                    received = await read_stream.receive()
                    assert isinstance(received, SessionMessage)
                    assert received.message == request
                    await write_stream.send(SessionMessage(response))
                    line = await _read_from(out_r)
                    assert jsonrpc_message_adapter.validate_json(line.decode().strip()) == response
                    os.close(in_w)
                    await write_stream.aclose()

        assert os.path.sameopenfile(0, in_r)
        assert os.path.sameopenfile(1, out_w)


@pytest.mark.anyio
async def test_a_refused_claim_releases_the_stream_it_already_took(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport refused halfway through claiming restores what it claimed first.

    The first transport claims only stdout; the second claims stdin, is refused on stdout, and must release stdin.
    """
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w), _pipe_planted_on_fd1(monkeypatch) as (_, out_w):
        with anyio.fail_after(5):
            async with stdio_server(stdin=anyio.AsyncFile(io.StringIO())) as (read_stream, write_stream):
                read_stream.close()
                with pytest.raises(RuntimeError, match="already claimed fd 1"):
                    async with stdio_server():
                        pytest.fail("unreachable")  # pragma: no cover

                # fd 0 is back on the protocol pipe, not the null device.
                assert os.path.sameopenfile(0, in_r)
                await write_stream.aclose()

        assert os.path.sameopenfile(1, out_w)
        os.close(in_w)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="atomic above-range dup is POSIX-only (F_DUPFD)")
async def test_the_claim_engages_even_when_stderr_is_closed(  # pragma: lax no cover
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process missing fd 2 still gets full isolation on POSIX.

    F_DUPFD allocates the wire duplicate above the standard range atomically, so
    the hole in slot 2 cannot capture it; the stdout diversion falls back to the
    null device. Windows has no atomic minfd dup: the duplicate can land in the
    hole and the transport degrades to serving in place (a documented residue),
    which is safe but not this test's isolation contract, and this test's blocking
    read of the still-piped fd 0 would then never return.
    """
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w), _pipe_planted_on_fd1(monkeypatch) as (out_r, out_w):
        saved2 = os.dup(2)
        os.close(2)
        try:
            with anyio.fail_after(5):
                async with stdio_server() as (read_stream, write_stream):
                    async with read_stream:  # pragma: no branch
                        # Claimed: fd 0 reads the null device, not the pipe.
                        devnull_probe = os.open(os.devnull, os.O_RDONLY)
                        try:
                            assert os.path.sameopenfile(0, devnull_probe)
                        finally:
                            os.close(devnull_probe)

                        os.write(in_w, _frame(request))
                        received = await read_stream.receive()
                        assert isinstance(received, SessionMessage)
                        assert received.message == request
                        await write_stream.send(SessionMessage(response))
                        line = await _read_from(out_r)
                        assert jsonrpc_message_adapter.validate_json(line.decode().strip()) == response
                        os.close(in_w)
                        await write_stream.aclose()

            assert os.path.sameopenfile(0, in_r)
            assert os.path.sameopenfile(1, out_w)
        finally:
            os.dup2(saved2, 2)
            os.close(saved2)


@pytest.mark.anyio
async def test_stdio_server_serves_in_place_when_the_diversion_cannot_be_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A diversion that cannot be opened leaves fd 0 untouched and serves in place."""
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w):
        os.write(in_w, _frame(request))
        os.close(in_w)
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        def failing_diversion() -> int:
            raise OSError("injected diversion failure")

        monkeypatch.setattr("mcp.server.stdio._open_stdin_diversion", failing_diversion)

        with anyio.fail_after(5):
            async with stdio_server() as (read_stream, write_stream):  # pragma: no branch
                async with read_stream:  # pragma: no branch
                    assert os.path.sameopenfile(0, in_r)
                    received = await read_stream.receive()
                    assert isinstance(received, SessionMessage)
                    assert received.message == request
                    await write_stream.aclose()


@pytest.mark.anyio
async def test_a_degraded_session_does_not_close_the_sys_stream_it_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transport's text layer never closes a buffer it does not own.

    Regression for the issue #1933 class: in the in-place paths the transport wraps
    the sys stream's own buffer, and wrapper garbage collection must not close it.
    """
    with _pipe_planted_on_fd0(monkeypatch) as (_, in_w):
        os.close(in_w)
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        def failing_dup_above_std(fd: int) -> int:
            raise OSError("forced degrade")

        monkeypatch.setattr("mcp.server.stdio._dup_above_std", failing_dup_above_std)

        with anyio.fail_after(5):
            async with stdio_server() as (read_stream, write_stream):
                read_stream.close()
                await write_stream.aclose()

        gc.collect()
        assert not sys.stdin.buffer.closed
        assert not sys.stdout.buffer.closed


class _GatedStdin(io.RawIOBase):
    """Raw stdin double: serves its frames, then blocks until released before EOF.

    A real client holds stdin open until it reads its responses; instant EOF races the
    dispatcher's EOF-time cancellation of in-flight handlers.
    """

    name = "<gated-stdin>"

    def __init__(self, payload: bytes) -> None:
        self._pending = payload
        self._released = threading.Event()

    def readable(self) -> bool:
        return True

    def readinto(self, b: Buffer) -> int:
        view = memoryview(b)
        if self._pending:
            n = min(len(view), len(self._pending))
            view[:n] = self._pending[:n]
            self._pending = self._pending[n:]
            return n
        # A missed release falls through to EOF after the bound.
        self._released.wait(5)
        return 0

    def release(self) -> None:
        self._released.set()


class _NotifyingStdout(io.RawIOBase):
    """Raw stdout double that counts newline-terminated lines and can be awaited on.

    close() is a no-op so the test can read what was written after run() tears down.
    """

    name = "<notifying-stdout>"

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._lines = 0
        self._cond = threading.Condition()

    def writable(self) -> bool:
        return True

    def write(self, b: Buffer) -> int:
        data = bytes(b)
        with self._cond:
            self._chunks.append(data)
            self._lines += data.count(b"\n")
            self._cond.notify_all()
        return len(data)

    def wait_for_lines(self, n: int, timeout: float = 5) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self._lines >= n, timeout)

    def getvalue(self) -> bytes:
        with self._cond:
            return b"".join(self._chunks)

    def close(self) -> None:
        pass


def _serve_stdio_and_collect(
    monkeypatch: pytest.MonkeyPatch, server: MCPServer, frames: list[JSONRPCRequest], responses: int
) -> list[JSONRPCMessage]:
    """Serve `frames` over process stdio and return the parsed response lines.

    Runs the blocking server.run("stdio") in a daemon thread and signals stdin EOF only after
    `responses` lines arrive - as a real client would - so handlers never race EOF cancellation.
    """
    payload = "".join(f.model_dump_json(by_alias=True, exclude_none=True) + "\n" for f in frames).encode()
    stdin = _GatedStdin(payload)
    stdout = _NotifyingStdout()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(stdout, encoding="utf-8"))

    def target() -> None:
        server.run("stdio")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    arrived = stdout.wait_for_lines(responses)
    stdin.release()
    thread.join(5)
    assert not thread.is_alive(), 'run("stdio") did not return after stdin EOF'
    assert arrived, f"expected {responses} response line(s); stdout carried: {stdout.getvalue()!r}"
    return [jsonrpc_message_adapter.validate_json(line) for line in stdout.getvalue().decode().splitlines()]


def test_mcpserver_run_stdio_serves_until_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """`MCPServer.run("stdio")` serves over process stdio and returns at stdin EOF."""
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")

    responses = _serve_stdio_and_collect(monkeypatch, MCPServer(name="RunStdioServer"), [ping], 1)

    assert responses == [JSONRPCResponse(jsonrpc="2.0", id=1, result={})]


def test_mcpserver_run_stdio_runs_lifespan_cleanup_after_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Code after `yield` in a lifespan runs when stdin EOF ends `run("stdio")`.

    Regression lock for the issue #1027 shutdown chain.
    """
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[None]:
        events.append("setup")
        try:
            yield
        finally:
            events.append("cleanup")

    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")

    server = MCPServer(name="LifespanStdioServer", lifespan=lifespan)
    responses = _serve_stdio_and_collect(monkeypatch, server, [ping], 1)

    assert events == ["setup", "cleanup"]
    assert responses == [JSONRPCResponse(jsonrpc="2.0", id=1, result={})]


def test_mcpserver_run_stdio_serves_a_modern_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """`MCPServer.run("stdio")` serves the modern era over process stdio.

    A `server/discover` probe (no initialize handshake), then a request served at the discovered version.
    """
    envelope = {
        PROTOCOL_VERSION_META_KEY: "2026-07-28",
        CLIENT_INFO_META_KEY: {"name": "probe", "version": "1.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    discover = JSONRPCRequest(jsonrpc="2.0", id=1, method="server/discover", params={"_meta": envelope})
    tools = JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/list", params={"_meta": envelope})

    responses = _serve_stdio_and_collect(monkeypatch, MCPServer(name="ModernStdioServer"), [discover, tools], 2)

    assert isinstance(responses[0], JSONRPCResponse) and responses[0].id == 1
    assert "2026-07-28" in responses[0].result["supportedVersions"]
    assert responses[0].result["serverInfo"]["name"] == "ModernStdioServer"
    assert isinstance(responses[1], JSONRPCResponse) and responses[1].id == 2
    # resultType is modern-only: proves the request was served at the discovered version.
    assert responses[1].result["tools"] == []
    assert responses[1].result["resultType"] == "complete"
