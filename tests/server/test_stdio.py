import io
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import TextIOWrapper
from pathlib import Path

import anyio
import anyio.abc
import pytest
from anyio.streams.buffered import BufferedByteReceiveStream
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    SERVER_INFO_META_KEY,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)
from typing_extensions import Buffer

from mcp.server import serve_stream
from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import newline_json_transport, stdio_server
from mcp.shared.message import SessionMessage


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """Run every async test in this module on both anyio backends; the sync
    `run("stdio")` tests drive their own loop in a worker thread and take neither."""
    return request.param


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


class _ByteStreamDouble(anyio.abc.ByteStream):
    """A minimal `ByteStream` over an inbound memory stream, recording what the framer writes.

    `broken=True` makes every send fail the way a peer that vanished does, so the
    framer's writer can be shown to end quietly instead of crashing the connection.
    """

    def __init__(self, inbound: anyio.abc.ObjectReceiveStream[bytes], *, broken: bool = False) -> None:
        self._inbound = inbound
        self._broken = broken
        self.sent: list[bytes] = []
        self.closed = False

    async def receive(self, max_bytes: int = 65536) -> bytes:
        try:
            return await self._inbound.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            raise anyio.EndOfStream from None

    async def send(self, item: bytes) -> None:
        if self._broken:
            raise anyio.BrokenResourceError
        self.sent.append(item)

    async def send_eof(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self.closed = True


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

    server = MCPServer(name="ModernStdioServer", version="1.2.3")
    responses = _serve_stdio_and_collect(monkeypatch, server, [discover, tools], 2)

    assert isinstance(responses[0], JSONRPCResponse) and responses[0].id == 1
    assert "2026-07-28" in responses[0].result["supportedVersions"]
    # Server identity travels as the result `_meta` stamp, not a DiscoverResult
    # body field (spec 2026-07-28, #3002).
    assert responses[0].result["_meta"][SERVER_INFO_META_KEY] == {"name": "ModernStdioServer", "version": "1.2.3"}
    assert isinstance(responses[1], JSONRPCResponse) and responses[1].id == 2
    # `resultType` is the modern-only wire field: its presence proves the
    # request was served at the discovered version, not the handshake era.
    assert responses[1].result["tools"] == []
    assert responses[1].result["resultType"] == "complete"


# --- newline_json_transport: the stdio framing over any byte stream --------------


@pytest.mark.anyio
async def test_custom_transport_over_a_unix_socket_needs_only_framing_plus_serve_stream(tmp_path: Path) -> None:
    """The whole custom-transport story: frame a real Unix socket with
    `newline_json_transport` and hand the streams to `serve_stream` - a raw
    JSON-RPC client on the other end gets a served answer, one frame per line."""
    server = MCPServer(name="socket-server")

    @server.tool()
    def add(a: int, b: int) -> str:
        """Add two numbers."""
        return str(a + b)

    socket_path = tmp_path / "mcp.sock"
    listener = await anyio.create_unix_listener(socket_path)
    connection_served = anyio.Event()

    async def handle(stream: anyio.abc.SocketStream) -> None:
        async with stream, newline_json_transport(stream) as (read_stream, write_stream):
            await serve_stream(server._lowlevel_server, read_stream, write_stream)  # pyright: ignore[reportPrivateUsage]
        connection_served.set()  # the driver returned once the client closed its end

    envelope = {
        PROTOCOL_VERSION_META_KEY: "2026-07-28",
        CLIENT_INFO_META_KEY: {"name": "socket-client", "version": "1.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    call = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={"name": "add", "arguments": {"a": 3, "b": 4}, "_meta": envelope},
    )
    line = b""
    async with listener, anyio.create_task_group() as tg:
        tg.start_soon(listener.serve, handle)
        with anyio.fail_after(5):
            async with await anyio.connect_unix(socket_path) as client:
                await client.send(call.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n")
                line = await BufferedByteReceiveStream(client).receive_until(b"\n", 1_000_000)
            # The client closed its socket: the driver sees EOF and ends the connection.
            await connection_served.wait()
        tg.cancel_scope.cancel()

    answer = jsonrpc_message_adapter.validate_json(line, by_name=False)
    assert isinstance(answer, JSONRPCResponse) and answer.id == 1
    assert answer.result["content"][0]["text"] == "7"


@pytest.mark.anyio
async def test_newline_json_transport_frames_lines_both_ways_and_survives_a_malformed_line() -> None:
    """One JSON-RPC message per line in both directions: a line that is not JSON-RPC
    reaches the read stream as an exception item and the frame after it is still delivered
    (one bad line costs one line, not the connection), outbound messages are written as
    exactly one line each, and closing the byte stream stays the caller's job."""
    peer_send, transport_side = anyio.create_memory_object_stream[bytes](8)
    good = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    reply = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    stream = _ByteStreamDouble(transport_side)

    async with (
        peer_send,
        transport_side,
        newline_json_transport(stream) as (read_stream, write_stream),
        read_stream,  # the driver's ends: a driver would own and close these
        write_stream,
    ):
        await peer_send.send(b"this is not json\n")
        await peer_send.send(good.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n")
        with anyio.fail_after(5):
            first = await read_stream.receive()
            second = await read_stream.receive()
            await write_stream.send(SessionMessage(reply))
            await anyio.wait_all_tasks_blocked()  # let the writer flush onto the byte stream
        peer_send.close()  # peer EOF: the framer ends its inbound stream
        with anyio.fail_after(5):
            assert [item async for item in read_stream] == []

    assert isinstance(first, Exception)
    assert isinstance(second, SessionMessage) and second.message == good
    assert stream.sent == [reply.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8") + b"\n"]
    assert not stream.closed  # the framer never closes the byte stream itself
    await stream.send_eof()
    assert stream.closed


@pytest.mark.anyio
async def test_newline_json_transport_writer_ends_quietly_when_the_peer_is_gone() -> None:
    """A write onto a byte stream whose peer has vanished ends the writer without an
    error escaping: outbound frames after that are undeliverable, not a crash."""
    peer_send, transport_side = anyio.create_memory_object_stream[bytes](8)
    stream = _ByteStreamDouble(transport_side, broken=True)

    async with (
        peer_send,
        transport_side,
        newline_json_transport(stream) as (read_stream, write_stream),
        read_stream,
        write_stream,
    ):
        with anyio.fail_after(5):
            await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=1, result={})))
            await anyio.wait_all_tasks_blocked()  # the writer hits the broken send and returns
    assert stream.sent == []


@pytest.mark.anyio
async def test_newline_json_transport_ends_the_read_side_on_an_oversized_frame() -> None:
    """A frame that overruns the bound cannot be resynchronised: the framer surfaces
    the overrun as an exception item and then ends the inbound stream (EOF)."""
    peer_send, transport_side = anyio.create_memory_object_stream[bytes](8)

    async with (
        peer_send,
        transport_side,
        newline_json_transport(_ByteStreamDouble(transport_side), max_frame_bytes=8) as (
            read_stream,
            write_stream,
        ),
        read_stream,  # the driver's ends: a driver would own and close these
        write_stream,
    ):
        await peer_send.send(b"x" * 32)  # no newline within the 8-byte bound
        with anyio.fail_after(5):
            items = [item async for item in read_stream]

    assert len(items) == 1 and isinstance(items[0], anyio.DelimiterNotFound)
