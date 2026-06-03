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
async def test_stdio_server_no_crlf_on_windows(monkeypatch: pytest.MonkeyPatch):
    """Verify stdout uses bare LF (\\n) line endings, not CRLF (\\r\\n).

    The MCP protocol uses newline-delimited JSON with \\n as the delimiter.
    On Windows, TextIOWrapper without newline="" translates \\n -> \\r\\n,
    corrupting the wire format. This test ensures the fix is effective on
    all platforms by going through the default sys.stdout.buffer path.
    """

    class NonClosingBytesIO(io.BytesIO):
        """BytesIO subclass that ignores close() so we can inspect data after
        the owning TextIOWrapper is closed."""

        def close(self) -> None:
            pass  # Keep the buffer open for inspection

    raw_stdin_buf = io.BytesIO(b"")
    raw_stdout_buf = NonClosingBytesIO()

    # Create a fake sys.stdin / sys.stdout that expose .buffer attributes
    # pointing to our BytesIO objects.  This exercises the real code path in
    # stdio_server() which accesses sys.stdin.buffer / sys.stdout.buffer.
    fake_stdin = TextIOWrapper(raw_stdin_buf, encoding="utf-8")
    fake_stdout = TextIOWrapper(raw_stdout_buf, encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    with anyio.fail_after(5):
        async with stdio_server() as (read_stream, write_stream):
            # Send a message through the server's write stream
            response = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
            session_message = SessionMessage(response)
            await write_stream.send(session_message)
            await write_stream.aclose()
            # Drain the read stream so the stdin_reader task can exit cleanly
            await read_stream.aclose()

    # The stdio_server wraps sys.stdout.buffer (= raw_stdout_buf) with its own
    # TextIOWrapper(newline="").  After the context manager exits, all data
    # should be flushed to raw_stdout_buf.
    raw_bytes = raw_stdout_buf.getvalue()
    assert raw_bytes, "Expected output bytes but got empty buffer"
    # Must end with bare \n, not \r\n
    assert raw_bytes.endswith(b"\n"), f"Output must end with LF: {raw_bytes!r}"
    assert not raw_bytes.endswith(b"\r\n"), f"Output must NOT contain CRLF: {raw_bytes!r}"
    # No \r anywhere in the output
    assert b"\r" not in raw_bytes, f"Output contains CR byte: {raw_bytes!r}"
