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
    """stdio_server frames JSON-RPC messages as one line each in both directions.

    Parses one message per stdin line and writes each outgoing message as exactly one
    line, driven over injected in-process streams.
    """
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
    """Non-UTF-8 stdin bytes surface as an in-stream exception without killing the stream.

    Invalid bytes are replaced with U+FFFD, fail JSON parsing, and arrive as an in-stream
    exception; subsequent valid messages are still processed.
    """
    # \xff\xfe are invalid UTF-8 start bytes.
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = io.BytesIO(b"\xff\xfe\n" + valid.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")

    # Replace sys.stdin with a wrapper whose .buffer is our raw bytes, so that
    # stdio_server()'s default path wraps it with errors='replace'.
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(raw_stdin, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    with anyio.fail_after(5):
        async with stdio_server() as (read_stream, write_stream):
            await write_stream.aclose()
            async with read_stream:  # pragma: no branch
                # First line: \xff\xfe -> U+FFFD U+FFFD -> JSON parse fails -> exception in stream
                first = await read_stream.receive()
                assert isinstance(first, Exception)

                # Second line: valid message still comes through
                second = await read_stream.receive()
                assert isinstance(second, SessionMessage)
                assert second.message == valid


@contextmanager
def _pipe_planted_on_fd0(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, int]]:
    """Plants a fresh pipe on the process's fd 0 and rebinds sys.stdin over it.

    Yields the pipe's (read_fd, write_fd). The caller owns the write end and
    must close it exactly once (every test does, to EOF the transport); the
    helper closes only what it created and still owns, so no descriptor is
    ever closed twice - a second close lands on a recycled fd number and
    destroys whatever unrelated file now lives there (pytest's capture files,
    in practice). Captures the real os.dup2 up front so teardown restores
    fd 0 even for tests that monkeypatch descriptor calls.
    """
    real_dup2 = os.dup2
    in_r, in_w = os.pipe()
    saved0 = os.dup(0)
    stdin_double = TextIOWrapper(open(0, "rb", closefd=False), encoding="utf-8")
    try:
        os.dup2(in_r, 0)
        monkeypatch.setattr(sys, "stdin", stdin_double)
        yield in_r, in_w
    finally:
        # Closed while its descriptor is still valid, so a later garbage
        # collection never does I/O on a recycled fd.
        stdin_double.close()
        real_dup2(saved0, 0)
        os.close(saved0)
        os.close(in_r)


def _frame(message: JSONRPCRequest | JSONRPCResponse) -> bytes:
    """One JSON-RPC message as the newline-terminated wire line the transport reads."""
    return (message.model_dump_json(by_alias=True, exclude_none=True) + "\n").encode()


@pytest.mark.anyio
async def test_stdio_server_takes_stdin_off_the_descriptor_table_while_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the real process stdin, the transport claims the protocol pipe and releases it on exit.

    SDK-defined behavior: while serving, fd 0 is the null device, so a child
    process that inherits it cannot consume protocol bytes and, on Windows,
    cannot hang at interpreter startup behind the transport's pending read
    (CPython gh-78961). The protocol still flows over the original pipe, and on
    exit fd 0 points back at it. Raw pipes are the subject here: the property
    under test is what the process's descriptor table looks like while serving.
    """
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w):
        out_r, out_w = os.pipe()  # captures responses via the sys.stdout double
        stdout_double = TextIOWrapper(open(out_w, "wb", closefd=False), encoding="utf-8")
        try:
            monkeypatch.setattr(sys, "stdout", stdout_double)

            request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
            response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
            with anyio.fail_after(5):
                async with stdio_server() as (read_stream, write_stream):
                    async with read_stream:
                        # fd 0 is the null device: instant EOF instead of protocol bytes. In a
                        # worker thread because a regression would leave fd 0 on the (empty)
                        # protocol pipe, and a blocked read on the loop thread would outlive
                        # fail_after; abandoning turns that into a red TimeoutError instead.
                        assert await anyio.to_thread.run_sync(os.read, 0, 1, abandon_on_cancel=True) == b""

                        # The protocol still flows over the original pipe.
                        os.write(in_w, _frame(request))
                        received = await read_stream.receive()
                        assert isinstance(received, SessionMessage)
                        assert received.message == request

                        await write_stream.send(SessionMessage(response))
                        # Worker thread + abandon for the same reason as the fd 0 read above.
                        line = await anyio.to_thread.run_sync(os.read, out_r, 65536, abandon_on_cancel=True)
                        assert jsonrpc_message_adapter.validate_json(line.decode().strip()) == response

                        os.close(in_w)  # EOF lets the reader finish so the context can exit
                        await write_stream.aclose()

                # Restored: fd 0 is a handle to the protocol pipe again, not the null
                # device. samestat degrades to a trivially-true comparison for pipes on
                # Windows (st_dev/st_ino are 0 there); the POSIX legs carry the assertion.
                assert os.path.sameopenfile(0, in_r)
        finally:
            stdout_double.close()
            os.close(out_r)
            os.close(out_w)


@pytest.mark.anyio
async def test_a_nested_stdio_server_does_not_clobber_the_first_transports_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the first default-stream transport claims stdin; a nested one serves in place.

    SDK-defined behavior: a second stdio_server() entered while the first is
    serving must not re-claim fd 0 (it would duplicate the null device and its
    restore would clobber the first transport's). The inner transport reads the
    in-place stdin - the null device while the outer one serves - and sees
    immediate EOF; after both exit, fd 0 is back on the protocol pipe.
    """
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w):
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        with anyio.fail_after(5):
            async with stdio_server() as (outer_read, outer_write):
                async with outer_read:
                    async with stdio_server() as (inner_read, inner_write):
                        async with inner_read:
                            with pytest.raises(anyio.EndOfStream):
                                await inner_read.receive()
                            await inner_write.aclose()

                    # The outer transport still owns the real pipe.
                    os.write(in_w, _frame(request))
                    received = await outer_read.receive()
                    assert isinstance(received, SessionMessage)
                    assert received.message == request

                    os.close(in_w)
                    await outer_write.aclose()

            assert os.path.sameopenfile(0, in_r)


@pytest.mark.anyio
@pytest.mark.parametrize("failing_call", ["dup", "dup2"])
async def test_stdio_server_reads_stdin_in_place_when_descriptor_isolation_fails(
    failing_call: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A descriptor-table failure while claiming stdin degrades to reading sys.stdin in place.

    SDK-defined behavior: isolation is best-effort; when duplicating fd 0 or
    retargeting it fails, the transport serves over the original stdin exactly
    as it did before isolation existed - observable as fd 0 still being the
    protocol pipe while serving. The dup2 variant fails after the private
    duplicate exists, covering its cleanup path.
    """
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    with _pipe_planted_on_fd0(monkeypatch) as (in_r, in_w):
        os.write(in_w, _frame(request))
        os.close(in_w)  # EOF after the one frame lets the reader finish
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        # Injections fire exactly once, at the transport's own call, then pass
        # through: pytest's capture machinery also calls os.dup/os.dup2 at
        # phase transitions, and a still-armed injector detonating there
        # corrupts capture for every later test in the process.
        if failing_call == "dup":
            real_dup = os.dup
            armed = [True]

            def failing_dup(fd: int) -> int:
                if fd == 0 and armed[0]:
                    armed[0] = False
                    raise OSError("injected descriptor failure")
                return real_dup(fd)

            monkeypatch.setattr(os, "dup", failing_dup)
        else:
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
                    # Isolation was skipped: fd 0 is still the protocol pipe,
                    # not the null device. (samestat degrades to trivially-true
                    # for pipes on Windows; the POSIX legs carry the assertion.)
                    assert os.path.sameopenfile(0, in_r)
                    # The spent injector passes calls through untouched.
                    os.close(os.dup(0))
                    received = await read_stream.receive()
                    assert isinstance(received, SessionMessage)
                    assert received.message == request
                    await write_stream.aclose()


@pytest.mark.anyio
async def test_stdio_server_exits_cleanly_when_the_stdin_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed fd 0 restore on exit is swallowed, not raised.

    SDK-defined behavior: the restore in stdio_server's finally must never mask
    the exception (or clean exit) that ended the transport. The context exits
    normally; the only trace is fd 0 remaining on the null device.
    """
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    with _pipe_planted_on_fd0(monkeypatch) as (_, in_w):
        os.write(in_w, _frame(request))
        os.close(in_w)
        monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

        # The claim's dup2 (first call) must succeed and only the restore's
        # dup2 (second call) fails; later calls pass through because pytest's
        # capture machinery also uses os.dup2 between test phases.
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

        # The restore was attempted (second dup2) and its failure swallowed:
        # the context exited cleanly with fd 0 left on the null device.
        assert dup2_calls[1] == (dup2_calls[1][0], 0)
        devnull_probe = os.open(os.devnull, os.O_RDONLY)
        try:
            assert os.path.sameopenfile(0, devnull_probe)
        finally:
            os.close(devnull_probe)


class _GatedStdin(io.RawIOBase):
    """Raw stdin double: serves its frames, then blocks until released before EOF.

    A real stdio client keeps stdin open until it has read the responses it is
    awaiting; an immediate EOF after the last frame races the dispatcher's
    EOF-time cancellation of in-flight handlers (only inline-handled methods
    would deterministically answer first). The blocked read sits in
    `stdio_server`'s reader worker thread and unblocks on `release()`.
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
        # A missed release falls through to EOF after the bound; the caller's
        # own response assertions then report what actually arrived.
        self._released.wait(5)
        return 0

    def release(self) -> None:
        self._released.set()


class _NotifyingStdout(io.RawIOBase):
    """Raw stdout double that counts newline-terminated lines and can be awaited on.

    Survives wrapper close (`close()` is a no-op) so the test can read what was
    written after `run()` has torn its TextIOWrapper down.
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

    Runs the blocking `server.run("stdio")` in a daemon thread (it creates its
    own event loop, so a sync test cannot arm `anyio.fail_after`) and signals
    stdin EOF only after `responses` lines arrive on stdout - the way a real
    client closes the pipe - so spawned in-flight handlers never race the
    dispatcher's EOF cancellation. The join bound turns a run loop that never
    returns on stdin EOF into a red test instead of a silent CI hang; an
    exception escaping `run()` still fails the test via pytest's
    unhandled-thread warning, escalated by `filterwarnings = ["error"]`.
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
    """`MCPServer.run("stdio")` serves over process stdio and returns at stdin EOF.

    Answers a request over the process's stdio and returns when stdin reaches EOF,
    rather than serving forever.
    """
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")

    responses = _serve_stdio_and_collect(monkeypatch, MCPServer(name="RunStdioServer"), [ping], 1)

    assert responses == [JSONRPCResponse(jsonrpc="2.0", id=1, result={})]


def test_mcpserver_run_stdio_runs_lifespan_cleanup_after_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Code after `yield` in a lifespan runs when stdin EOF ends `run("stdio")`.

    Regression lock for the issue #1027 shutdown chain: the run loop must end on
    stdin EOF and unwind the lifespan rather than be killed before returning.
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

    A `server/discover` probe gets a DiscoverResult (no initialize handshake)
    and a subsequent envelope-bearing request is served at the discovered
    version - the wire exchange `Client(mode='auto')` drives against a stdio
    server.
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
    # `resultType` is the modern-only wire field: its presence proves the
    # request was served at the discovered version, not the handshake era.
    assert responses[1].result["tools"] == []
    assert responses[1].result["resultType"] == "complete"
