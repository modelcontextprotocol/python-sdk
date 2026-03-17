import io

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
async def test_stdio_server_with_buffer_size():
    """Test that stdio_server works with configurable buffer sizes."""
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
        JSONRPCRequest(jsonrpc="2.0", id=2, method="ping"),
        JSONRPCRequest(jsonrpc="2.0", id=3, method="ping"),
    ]

    for message in messages:
        stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    async with stdio_server(
        stdin=anyio.AsyncFile(stdin),
        stdout=anyio.AsyncFile(stdout),
        read_stream_buffer_size=5,
        write_stream_buffer_size=5,
    ) as (read_stream, write_stream):
        received_messages: list[JSONRPCMessage] = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message
                received_messages.append(message.message)
                if len(received_messages) == 3:
                    break

        assert len(received_messages) == 3
        for i, msg in enumerate(received_messages, 1):
            assert msg == JSONRPCRequest(jsonrpc="2.0", id=i, method="ping")
        await write_stream.aclose()


@pytest.mark.anyio
async def test_stdio_server_buffered_does_not_block_reader():
    """Test that a non-zero buffer allows stdin_reader to continue reading
    even when the consumer is slow to process messages.

    With buffer_size=0, the reader blocks on send() until the consumer calls
    receive(). With buffer_size>0, the reader can queue messages ahead.
    """
    stdin = io.StringIO()
    stdout = io.StringIO()

    num_messages = 5
    for i in range(1, num_messages + 1):
        msg = JSONRPCRequest(jsonrpc="2.0", id=i, method="ping")
        stdin.write(msg.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    async with stdio_server(
        stdin=anyio.AsyncFile(stdin),
        stdout=anyio.AsyncFile(stdout),
        read_stream_buffer_size=num_messages,
    ) as (read_stream, write_stream):
        # Give the reader time to buffer all messages
        await anyio.sleep(0.1)

        received: list[JSONRPCMessage] = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message
                received.append(message.message)
                # Simulate slow processing
                await anyio.sleep(0.01)
                if len(received) == num_messages:
                    break

        assert len(received) == num_messages
        await write_stream.aclose()
