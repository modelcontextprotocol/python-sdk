import io
import os
import sys
import tempfile
import warnings
from io import TextIOWrapper

import anyio
import pytest

from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse, jsonrpc_message_adapter


@pytest.mark.anyio
async def test_stdio_server():
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
        JSONRPCResponse(jsonrpc="2.0", id=2, result={}),
    ]

    for message in messages:
        stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    async with stdio_server(stdin=anyio.AsyncFile(stdin), stdout=anyio.AsyncFile(stdout)) as (
        read_stream,
        write_stream,
    ):
        received_messages: list[JSONRPCMessage] = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):  # pragma: no cover
                    raise message
                received_messages.append(message.message)
                if len(received_messages) == 2:
                    break

        # Verify received messages
        assert len(received_messages) == 2
        assert received_messages[0] == JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        assert received_messages[1] == JSONRPCResponse(jsonrpc="2.0", id=2, result={})

        # Test sending responses from the server
        responses = [
            JSONRPCRequest(jsonrpc="2.0", id=3, method="ping"),
            JSONRPCResponse(jsonrpc="2.0", id=4, result={}),
        ]

        async with write_stream:
            for response in responses:
                session_message = SessionMessage(response)
                await write_stream.send(session_message)

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    received_responses = [jsonrpc_message_adapter.validate_json(line.strip()) for line in output_lines]
    assert len(received_responses) == 2
    assert received_responses[0] == JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
    assert received_responses[1] == JSONRPCResponse(jsonrpc="2.0", id=4, result={})


@pytest.mark.anyio
async def test_stdio_server_invalid_utf8(monkeypatch: pytest.MonkeyPatch):
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


@pytest.mark.anyio
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_stdio_server_does_not_close_real_stdio(monkeypatch: pytest.MonkeyPatch):
    """Verify that stdio_server does not close the real stdin/stdout.

    Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/1933.
    When using the default stdin/stdout (i.e., not passing custom streams),
    the server should duplicate file descriptors so that closing the wrapper
    does not close sys.stdin/sys.stdout.
    """
    # Create temp files to use as stdin/stdout (need real file descriptors)
    with tempfile.NamedTemporaryFile(delete=False) as tmp_stdin:
        tmp_stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        tmp_stdin_path = tmp_stdin.name

    with tempfile.NamedTemporaryFile(delete=False) as tmp_stdout:
        tmp_stdout_path = tmp_stdout.name

    stdin_wrapper = None
    stdout_wrapper = None

    try:
        # Open the files and create wrappers that look like sys.stdin/stdout
        stdin_file = open(tmp_stdin_path, "rb")
        stdout_file = open(tmp_stdout_path, "wb")

        stdin_wrapper = TextIOWrapper(stdin_file, encoding="utf-8")
        stdout_wrapper = TextIOWrapper(stdout_file, encoding="utf-8")

        monkeypatch.setattr(sys, "stdin", stdin_wrapper)
        monkeypatch.setattr(sys, "stdout", stdout_wrapper)

        # Run the server with default stdin/stdout
        with anyio.fail_after(5):
            async with stdio_server() as (read_stream, write_stream):
                await write_stream.aclose()
                async with read_stream:
                    msg = await read_stream.receive()
                    assert isinstance(msg, SessionMessage)

        # After server exits, verify the original stdin/stdout are still usable
        # The monkeypatched sys.stdin/stdout should NOT be closed
        assert not stdin_wrapper.closed, "sys.stdin was closed by stdio_server"
        assert not stdout_wrapper.closed, "sys.stdout was closed by stdio_server"

    finally:
        # Clean up
        if stdin_wrapper and not stdin_wrapper.closed:
            stdin_wrapper.close()
        if stdout_wrapper and not stdout_wrapper.closed:
            stdout_wrapper.close()
        os.unlink(tmp_stdin_path)
        os.unlink(tmp_stdout_path)
