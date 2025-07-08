import shutil

import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

tee: str = shutil.which("tee")  # type: ignore
python: str = shutil.which("python")  # type: ignore


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_context_manager_exiting():
    async with stdio_client(StdioServerParameters(command=tee)) as (_, _):
        pass


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_client():
    server_parameters = StdioServerParameters(command=tee)

    async with stdio_client(server_parameters) as (read_stream, write_stream):
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
        assert read_messages[0] == JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"))
        assert read_messages[1] == JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={}))


@pytest.mark.anyio
async def test_stdio_client_bad_path():
    """Check that the connection doesn't hang if process errors."""
    server_params = StdioServerParameters(command="python", args=["-c", "non-existent-file.py"])
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # The session should raise an error when the connection closes
            with pytest.raises(McpError) as exc_info:
                await session.initialize()

            # Check that we got a connection closed error
            assert exc_info.value.error.code == CONNECTION_CLOSED
            assert "Connection closed" in exc_info.value.error.message


@pytest.mark.anyio
async def test_stdio_client_nonexistent_command():
    """Test that stdio_client raises an error for non-existent commands."""
    # Create a server with a non-existent command
    server_params = StdioServerParameters(
        command="/path/to/nonexistent/command",
        args=["--help"],
    )

    # Should raise an error when trying to start the process
    with pytest.raises(Exception) as exc_info:
        async with stdio_client(server_params) as (_, _):
            pass

    # The error should indicate the command was not found
    error_message = str(exc_info.value)
    assert (
        "nonexistent" in error_message
        or "not found" in error_message.lower()
        or "cannot find the file" in error_message.lower()  # Windows error message
    )
