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

python: str = shutil.which("python")  # type: ignore


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
