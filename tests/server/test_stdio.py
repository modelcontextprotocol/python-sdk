import io
import sys
import tempfile
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import pytest

from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse, jsonrpc_message_adapter


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
async def test_stdio_server_supports_fileno_less_standard_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default path supports in-memory stdio replacements without fileno()."""
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = io.BytesIO(request.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    raw_stdout = io.BytesIO()

    test_stdin = TextIOWrapper(raw_stdin, encoding="utf-8")
    test_stdout = TextIOWrapper(raw_stdout, encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", test_stdin)
    monkeypatch.setattr(sys, "stdout", test_stdout)

    with anyio.fail_after(5):
        async with stdio_server() as (read_stream, write_stream):
            await write_stream.aclose()
            async with read_stream:  # pragma: no branch
                message = await read_stream.receive()
                assert isinstance(message, SessionMessage)
                assert message.message == request


@pytest.mark.anyio
async def test_stdio_server_invalid_utf8() -> None:
    """Non-UTF-8 stdin bytes surface as an in-stream exception without killing the stream.

    Invalid bytes are replaced with U+FFFD, fail JSON parsing, and arrive as an in-stream
    exception; subsequent valid messages are still processed.
    """
    # \xff\xfe are invalid UTF-8 start bytes.
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = tempfile.TemporaryFile()
    raw_stdin.write(b"\xff\xfe\n" + valid.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    raw_stdin.seek(0)
    raw_stdout = tempfile.TemporaryFile()

    # Replace sys.stdin/stdout with wrappers backed by real file descriptors so
    # stdio_server()'s default path can duplicate them without closing the
    # original process-level streams.
    original_stdin = sys.stdin
    original_stdout = sys.stdout
    test_stdin = TextIOWrapper(raw_stdin, encoding="utf-8")
    test_stdout = TextIOWrapper(raw_stdout, encoding="utf-8")
    sys.stdin = test_stdin
    sys.stdout = test_stdout

    try:
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

        assert not sys.stdin.closed
        assert not sys.stdout.closed
        sys.stdout.write("stdio still open")
    finally:
        sys.stdin = original_stdin
        sys.stdout = original_stdout
        test_stdin.close()
        test_stdout.close()


class _KeepOpenBytesIO(io.BytesIO):
    """A BytesIO that survives its TextIOWrapper being closed.

    Lets the test read what was written after `run()` has torn the wrapper down.
    """

    def close(self) -> None:
        pass


def _run_stdio_bounded(server: MCPServer) -> None:
    """Run the blocking `server.run("stdio")` in a daemon thread joined with a 5s bound.

    `run()` creates its own event loop, so a sync test cannot arm `anyio.fail_after`;
    the join timeout turns a run loop that never returns on stdin EOF into a red test
    instead of a silent CI hang. An exception escaping `run()` still fails the test:
    pytest's unhandled-thread warning is escalated by `filterwarnings = ["error"]`.
    """

    def target() -> None:
        server.run("stdio")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), 'run("stdio") did not return after stdin EOF'


def test_mcpserver_run_stdio_serves_until_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """`MCPServer.run("stdio")` serves over process stdio and returns at stdin EOF.

    Answers a request over the process's stdio and returns when stdin reaches EOF,
    rather than serving forever.
    """
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    stdin_bytes = io.BytesIO(ping.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    captured = _KeepOpenBytesIO()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(captured, encoding="utf-8"))

    _run_stdio_bounded(MCPServer(name="RunStdioServer"))

    response = jsonrpc_message_adapter.validate_json(captured.getvalue().decode().strip())
    assert response == JSONRPCResponse(jsonrpc="2.0", id=1, result={})


def test_mcpserver_run_stdio_runs_lifespan_cleanup_after_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Code after `yield` in a lifespan runs when stdin EOF ends `run("stdio")`.

    Regression lock for the issue #1027 shutdown chain: the run loop must end on
    stdin EOF and unwind the lifespan rather than be killed before returning.
    """
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncGenerator[None, None]:
        events.append("setup")
        try:
            yield
        finally:
            events.append("cleanup")

    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    stdin_bytes = io.BytesIO(ping.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    captured = _KeepOpenBytesIO()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(captured, encoding="utf-8"))

    _run_stdio_bounded(MCPServer(name="LifespanStdioServer", lifespan=lifespan))

    assert events == ["setup", "cleanup"]
    response = jsonrpc_message_adapter.validate_json(captured.getvalue().decode().strip())
    assert response == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
