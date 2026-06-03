import io
import sys
import threading
from collections.abc import AsyncIterator
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
    """stdio_server parses one JSON-RPC message per stdin line and writes each
    outgoing message as exactly one line, driven over injected in-process streams."""
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
    """Non-UTF-8 bytes on stdin must not crash the server.

    Invalid bytes are replaced with U+FFFD, which then fails JSON parsing and
    is delivered as an in-stream exception. Subsequent valid messages must
    still be processed.
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


class _KeepOpenBytesIO(io.BytesIO):
    """A BytesIO that survives its TextIOWrapper being closed, so the test can read
    what was written after `run()` has torn the wrapper down."""

    def close(self) -> None:
        pass


def _run_stdio_bounded(server: MCPServer) -> None:
    """Call the blocking `server.run("stdio")` with a deadline, failing instead of hanging.

    `run()` creates its own event loop, so a sync test has no async frame to arm
    `anyio.fail_after` from; a daemon thread joined with the suite's standard 5s
    bound is the sync analogue. `join()` returns as soon as `run()` does — the
    timeout only fires if the run loop regresses into never returning on stdin EOF,
    turning a silent CI hang into a red test. An exception escaping `run()` fails
    the test too: pytest reports it as `PytestUnhandledThreadExceptionWarning`,
    which `filterwarnings = ["error"]` escalates.
    """

    def target() -> None:
        server.run("stdio")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), 'run("stdio") did not return after stdin EOF'


def test_mcpserver_run_stdio_serves_until_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """`MCPServer.run("stdio")` answers a request over the process's stdio and returns
    when stdin reaches EOF, rather than serving forever."""
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

    Regression lock for the shutdown chain behind issue #1027: the run loop must end
    on stdin EOF and unwind the lifespan — were the process killed before the run
    loop returned, the cleanup entry would never be appended.
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
    stdin_bytes = io.BytesIO(ping.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    captured = _KeepOpenBytesIO()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(captured, encoding="utf-8"))

    _run_stdio_bounded(MCPServer(name="LifespanStdioServer", lifespan=lifespan))

    assert events == ["setup", "cleanup"]
    response = jsonrpc_message_adapter.validate_json(captured.getvalue().decode().strip())
    assert response == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
