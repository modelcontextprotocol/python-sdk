import io
import os
import sys
from unittest.mock import MagicMock, patch

import anyio
import pytest

from mcp.server.stdio import _create_stdin_eof_monitor, stdio_server
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


def test_create_stdin_eof_monitor_returns_none_on_win32():
    """On Windows, the EOF monitor is not supported."""
    tg = MagicMock()
    with patch.object(sys, "platform", "win32"):
        result = _create_stdin_eof_monitor(tg)
    assert result is None


def test_create_stdin_eof_monitor_returns_none_when_fileno_fails():
    """When stdin.buffer.fileno() raises, the monitor returns None."""
    tg = MagicMock()
    mock_buffer = MagicMock()
    mock_buffer.fileno.side_effect = io.UnsupportedOperation("redirected stdin")
    with patch.object(sys, "platform", "linux"), patch.object(sys, "stdin", MagicMock(buffer=mock_buffer)):
        result = _create_stdin_eof_monitor(tg)
    assert result is None


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="select.poll not available on Windows")
async def test_stdin_eof_monitor_detects_hangup():  # pragma: lax no cover
    """The EOF monitor cancels the task group when stdin pipe closes."""
    read_fd, write_fd = os.pipe()
    try:
        mock_buffer = MagicMock()
        mock_buffer.fileno.return_value = read_fd

        with patch.object(sys, "platform", "linux"), patch.object(sys, "stdin", MagicMock(buffer=mock_buffer)):
            async with anyio.create_task_group() as tg:
                monitor = _create_stdin_eof_monitor(tg)
                assert monitor is not None
                tg.start_soon(monitor)

                # Close the write end to trigger POLLHUP on read end
                os.close(write_fd)
                write_fd = -1

                # Wait for the monitor to cancel the task-group scope.
                with anyio.fail_after(5):
                    while not tg.cancel_scope.cancel_called:
                        await anyio.sleep(0.05)
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="select.poll not available on Windows")
async def test_stdin_eof_monitor_ignores_pollin_events():  # pragma: lax no cover
    """The monitor ignores POLLIN events (data available) and only reacts to hangup/error."""
    read_fd, write_fd = os.pipe()
    try:
        mock_buffer = MagicMock()
        mock_buffer.fileno.return_value = read_fd

        with patch.object(sys, "platform", "linux"), patch.object(sys, "stdin", MagicMock(buffer=mock_buffer)):
            async with anyio.create_task_group() as tg:
                monitor = _create_stdin_eof_monitor(tg)
                assert monitor is not None
                tg.start_soon(monitor)

                # Write data to trigger POLLIN (not POLLHUP)
                os.write(write_fd, b"hello\n")

                # Give the monitor time to process the POLLIN event
                await anyio.sleep(0.3)

                # Monitor should NOT have cancelled since POLLIN alone isn't a hangup
                assert not tg.cancel_scope.cancel_called

                # Now close write end to trigger POLLHUP
                os.close(write_fd)
                write_fd = -1

                # Wait for the monitor to detect POLLHUP and cancel.
                with anyio.fail_after(5):
                    while not tg.cancel_scope.cancel_called:  # pragma: no branch
                        await anyio.sleep(0.05)
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)
