import io
import json
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import pytest
from mcp_types import (
    INVALID_REQUEST,
    PARSE_ERROR,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)

from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import _error_response_from_parse_failure, _request_id_from_raw_message, stdio_server
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
    """Non-UTF-8 stdin bytes produce an error response without killing the stream.

    Invalid bytes are replaced with U+FFFD, then fail JSON parsing and are returned
    as a JSON-RPC parse error. Subsequent valid messages are still processed.
    """
    # \xff\xfe are invalid UTF-8 start bytes.
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = io.BytesIO(b"\xff\xfe\n" + valid.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")

    # Replace sys.stdin with a wrapper whose .buffer is our raw bytes, so that
    # stdio_server()'s default path wraps it with errors='replace'.
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(raw_stdin, encoding="utf-8"))
    stdout = io.StringIO()

    with anyio.fail_after(5):
        async with stdio_server(stdout=anyio.AsyncFile(stdout)) as (read_stream, write_stream):
            async with read_stream:  # pragma: no branch
                # First line: \xff\xfe -> U+FFFD U+FFFD -> JSON parse fails -> error response on stdout
                first = await read_stream.receive()
                assert isinstance(first, SessionMessage)
                assert first.message == valid

            await write_stream.aclose()

    stdout.seek(0)
    output = stdout.read()
    error = jsonrpc_message_adapter.validate_json(output.strip())
    assert isinstance(error, JSONRPCError)
    assert error.id is None
    assert error.error.code == PARSE_ERROR


@pytest.mark.anyio
async def test_stdio_server_parse_error_completes_id_bearing_request() -> None:
    params: object = {"leaf": True}
    for index in reversed(range(256)):
        params = {f"p{index}": params}
    line = json.dumps({"jsonrpc": "2.0", "id": 900256, "method": "ping", "params": params}) + "\n"

    stdin = io.StringIO(line)
    stdout = io.StringIO()

    with anyio.fail_after(5):
        async with stdio_server(stdin=anyio.AsyncFile(stdin), stdout=anyio.AsyncFile(stdout)) as (
            read_stream,
            write_stream,
        ):
            async with read_stream:
                with pytest.raises(anyio.EndOfStream):
                    await read_stream.receive()
            await write_stream.aclose()

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 1

    response = jsonrpc_message_adapter.validate_json(output_lines[0].strip())
    assert isinstance(response, JSONRPCError)
    assert response.id == 900256
    assert response.error.code == PARSE_ERROR
    assert "Parse error" in response.error.message


def test_stdio_request_id_recovery_edges() -> None:
    assert _request_id_from_raw_message('{"jsonrpc":"2.0","id":"abc","method":"ping","params":[') == "abc"
    assert _request_id_from_raw_message('{"jsonrpc":"2.0","id":42,"method":"ping","params":[') == 42
    assert _request_id_from_raw_message('{"jsonrpc":"2.0","id":-7,"method":1}') == -7
    assert _request_id_from_raw_message('{"jsonrpc":"2.0","id":null,"method":1}') is None
    assert _request_id_from_raw_message("[]") is None


def test_stdio_invalid_request_response_preserves_string_id() -> None:
    line = '{"jsonrpc":"2.0","id":"bad-method","method":1}'
    with pytest.raises(Exception) as exc_info:
        jsonrpc_message_adapter.validate_json(line)

    response = _error_response_from_parse_failure(line, exc_info.value)

    assert isinstance(response.message, JSONRPCError)
    assert response.message.id == "bad-method"
    assert response.message.error.code == INVALID_REQUEST
    assert "Invalid request" in response.message.error.message


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
