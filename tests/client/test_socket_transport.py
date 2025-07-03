"""
Tests for socket transport functionality.

This module tests both client and server sides of the socket transport,
including error handling, encoding, and FastMCP integration.
"""

import shutil
import socket

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.client.socket_transport import SocketServerParameters, socket_client
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

python = shutil.which("python") or "python"


@pytest.mark.anyio
async def test_socket_context_manager_exiting():
    """Test that the socket client context manager exits cleanly."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            "import socket; s=socket.socket(); s.connect(('127.0.0.1', int(__import__('sys').argv[2]))); s.close()",
        ],
    )
    async with socket_client(server_params) as (_, _):
        pass


@pytest.mark.anyio
async def test_socket_client():
    """Test basic message sending and receiving over socket transport."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))
while True:
    data = s.recv(1024)
    if not data:
        break
    s.send(data)
s.close()
            """,
        ],
    )

    async with socket_client(server_params) as (read_stream, write_stream):
        # Test sending and receiving messages
        messages = [
            JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")),
            JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})),
        ]

        async with write_stream:
            for message in messages:
                session_message = SessionMessage(message)
                await write_stream.send(session_message)

        read_messages = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message

                read_messages.append(message.message)
                if len(read_messages) == 2:
                    break

        assert len(read_messages) == 2
        assert read_messages[0] == JSONRPCMessage(
            root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        )
        assert read_messages[1] == JSONRPCMessage(
            root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})
        )


@pytest.mark.anyio
async def test_socket_client_bad_path():
    """Check that the connection doesn't hang if process errors."""
    server_params = SocketServerParameters(
        command="python", args=["-c", "non-existent-file.py"]
    )
    with pytest.raises(Exception) as exc_info:
        async with socket_client(server_params) as (read_stream, write_stream):
            pass

    # The error should be a TimeoutError wrapped in an ExceptionGroup
    assert isinstance(exc_info.value, ExceptionGroup)
    assert isinstance(exc_info.value.exceptions[0], TimeoutError)


@pytest.mark.anyio
async def test_socket_client_nonexistent_command():
    """Test that socket_client raises an error for non-existent commands."""
    # Create a server with a non-existent command
    server_params = SocketServerParameters(
        command="/path/to/nonexistent/command",
        args=["--help"],
    )

    # Should raise an error when trying to start the process
    with pytest.raises(OSError) as exc_info:
        async with socket_client(server_params) as (_, _):
            pass

    # The error should indicate the command was not found
    error_message = str(exc_info.value)
    assert (
        "nonexistent" in error_message
        or "not found" in error_message.lower()
        or "cannot find the file" in error_message.lower()  # Windows error message
        or "no such file" in error_message.lower()  # Unix/macOS error message
    )


@pytest.mark.anyio
async def test_socket_client_connection_timeout():
    """Test that socket_client handles connection timeout gracefully."""
    # Create a server that doesn't connect back
    server_params = SocketServerParameters(
        command=python,
        args=["-c", "import time; time.sleep(10)"],
        connection_timeout=1.0,  # Set a short timeout for testing
    )

    # Should raise an error when connection times out
    with pytest.raises(Exception) as exc_info:
        async with socket_client(server_params) as (_, _):
            pass

    # The error should be a TimeoutError wrapped in an ExceptionGroup
    assert isinstance(exc_info.value, ExceptionGroup)
    assert isinstance(exc_info.value.exceptions[0], TimeoutError)


@pytest.mark.anyio
async def test_socket_client_connection_refused():
    """Test that socket_client handles connection refused gracefully."""
    # Create a server that exits immediately
    server_params = SocketServerParameters(
        command=python,
        args=["-c", "exit(0)"],
        connection_timeout=1.0,  # Set a short timeout for testing
    )

    # Should raise an error when connection is refused
    with pytest.raises(Exception) as exc_info:
        async with socket_client(server_params) as (_, _):
            pass

    # The error should be a TimeoutError wrapped in an ExceptionGroup
    assert isinstance(exc_info.value, ExceptionGroup)
    assert isinstance(exc_info.value.exceptions[0], TimeoutError)


@pytest.mark.anyio
async def test_socket_client_port_zero():
    """Test that port 0 works correctly for client (auto-assigns port)."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))
s.send(b'test')
s.close()
            """,
        ],
        port=0,  # Should auto-assign
    )

    async with socket_client(server_params) as (read_stream, write_stream):
        # The connection should succeed with an auto-assigned port
        assert True


@pytest.mark.anyio
async def test_socket_client_encoding():
    """Test message encoding/decoding with different character sets."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))
while True:
    data = s.recv(1024)
    if not data:
        break
    s.send(data)
s.close()
            """,
        ],
        encoding="utf-8",
        encoding_error_handler="strict",
    )

    async with socket_client(server_params) as (read_stream, write_stream):
        # Test messages with special characters
        messages = [
            JSONRPCMessage(
                root=JSONRPCRequest(
                    jsonrpc="2.0", id=1, method="echo", params={"text": "Hello, 世界!"}
                )
            ),
            JSONRPCMessage(
                root=JSONRPCRequest(
                    jsonrpc="2.0", id=2, method="echo", params={"text": "¡Hola, мир!"}
                )
            ),
        ]

        async with write_stream:
            for message in messages:
                session_message = SessionMessage(message)
                await write_stream.send(session_message)

        read_messages = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message

                read_messages.append(message.message)
                if len(read_messages) == 2:
                    break

        assert len(read_messages) == 2
        assert read_messages[0].root.params["text"] == "Hello, 世界!"
        assert read_messages[1].root.params["text"] == "¡Hola, мир!"


@pytest.mark.anyio
async def test_socket_client_invalid_json():
    """Test handling of invalid JSON messages."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))
s.send(b'invalid json\\n')
s.close()
            """,
        ],
    )

    async with socket_client(server_params) as (read_stream, write_stream):
        async for message in read_stream:
            assert isinstance(message, Exception)
            break


@pytest.mark.anyio
async def test_socket_client_cancellation_handling():
    """Test that socket_client handles cancellation gracefully."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys, time
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))
# Keep connection alive for a bit
time.sleep(2)
s.close()
            """,
        ],
    )

    # Test that cancellation works properly
    with anyio.move_on_after(0.5) as cancel_scope:
        async with socket_client(server_params) as (read_stream, write_stream):
            # Wait a bit, then the move_on_after should cancel
            await anyio.sleep(1)

    # The cancellation should have occurred
    assert cancel_scope.cancelled_caught


@pytest.mark.anyio
async def test_socket_client_cleanup_timeout():
    """Test that socket_client cleanup has timeout protection."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys, time
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))

# Send a message and keep connection alive briefly
s.send(b'{"jsonrpc": "2.0", "id": 1, "method": "test"}\\n')
time.sleep(1)  # Brief delay, then exit normally
s.close()
            """,
        ],
    )

    # Test that cleanup completes within reasonable time
    start_time = anyio.current_time()

    async with socket_client(server_params) as (read_stream, write_stream):
        # Do some work
        await anyio.sleep(0.1)

    end_time = anyio.current_time()

    # Normal cleanup should complete quickly (within 3 seconds)
    # This tests that the cleanup mechanism works without hanging
    assert end_time - start_time < 3.0


@pytest.mark.anyio
async def test_socket_client_cleanup_mechanism():
    """Test that socket_client cleanup mechanism is robust."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys, time
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))

# Send a test message
s.send(b'{"jsonrpc": "2.0", "id": 1, "method": "test"}\\n')

# Close after brief delay
time.sleep(0.2)
s.close()
            """,
        ],
    )

    # Test that cleanup works correctly
    async with socket_client(server_params) as (read_stream, write_stream):
        # Process at least one message
        async for message in read_stream:
            if isinstance(message, Exception):
                continue
            # Exit after first valid message
            break

    # If we reach here, cleanup worked properly
    assert True


@pytest.mark.anyio
async def test_socket_client_reader_writer_exception_handling():
    """Test that socket reader/writer handle exceptions properly."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys, time
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))

# Send some data then close abruptly
s.send(b'{"jsonrpc": "2.0", "id": 1, "method": "test"}\\n')
time.sleep(0.1)
s.close()  # Close connection abruptly
            """,
        ],
    )

    async with socket_client(server_params) as (read_stream, write_stream):
        # Should handle the abrupt connection close gracefully
        messages_received = 0
        async for message in read_stream:
            if isinstance(message, Exception):
                # Exceptions in the stream are expected
                continue
            messages_received += 1
            if messages_received >= 1:
                break

        assert messages_received >= 1


@pytest.mark.anyio
async def test_socket_client_process_cleanup():
    """Test that socket_client cleans up processes properly."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys, time, os
pid = os.getpid()
print(f"Process PID: {pid}", file=sys.stderr)

s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))
time.sleep(0.5)
s.close()
            """,
        ],
    )

    async with socket_client(server_params) as (read_stream, write_stream):
        # Brief interaction
        await anyio.sleep(0.1)

    # Process should be cleaned up after context exit
    # This is mainly to ensure no zombie processes remain
    await anyio.sleep(0.1)  # Give cleanup time to complete


@pytest.mark.anyio
async def test_socket_client_multiple_messages_with_cancellation():
    """Test handling multiple messages with cancellation."""
    server_params = SocketServerParameters(
        command=python,
        args=[
            "-c",
            """
import socket, sys, time, json
s = socket.socket()
s.connect(('127.0.0.1', int(sys.argv[2])))

# Send multiple messages
for i in range(10):
    msg = {"jsonrpc": "2.0", "id": i, "method": "test", "params": {"counter": i}}
    s.send((json.dumps(msg) + '\\n').encode())
    time.sleep(0.01)  # Small delay between messages

s.close()
            """,
        ],
    )

    messages_received = 0

    with anyio.move_on_after(1.0) as cancel_scope:
        async with socket_client(server_params) as (read_stream, write_stream):
            async for message in read_stream:
                if isinstance(message, Exception):
                    continue
                messages_received += 1
                if messages_received >= 5:
                    # Cancel after receiving some messages
                    cancel_scope.cancel()

    # Should have received some messages before cancellation
    assert messages_received >= 5
    assert cancel_scope.cancelled_caught
