import io
import sys
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
async def test_stdio_server_survives_stdin_eof(monkeypatch: pytest.MonkeyPatch):
    """Regression: server must survive transient client stdin close.

    When the MCP client closes its end of stdin between connection cycles,
    sys.stdin.buffer.readline() returns an empty string.  With anyio.wrap_file()
    this triggers StopAsyncIteration in the ``async for`` loop, killing the
    entire read loop.  The fix uses a blocking ``run_sync(raw_stdin.readline)``
    loop that treats an empty read as a transient condition and keeps waiting.
    """
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = io.BytesIO(
        valid.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n"
    )

    monkeypatch.setattr(sys, "stdin", TextIOWrapper(raw_stdin, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    with anyio.fail_after(5):
        async with stdio_server() as (read_stream, write_stream):
            await write_stream.aclose()
            async with read_stream:  # pragma: no branch
                # Valid message arrives
                first = await read_stream.receive()
                assert isinstance(first, SessionMessage)
                assert first.message == valid

                # Simulate client disconnect: stdin returns EOF.
                # Under the old anyio.wrap_file() path, this would have
                # already killed the read loop.  Under the fix, the
                # blocking readline() loop simply waits for more data.
                # The read_stream receive below would hang forever if
                # the server were dead — but since it's alive, the
                # context exit (via aclose) will cleanly tear us down.
            # If we reach here without timeout, the server survived.

