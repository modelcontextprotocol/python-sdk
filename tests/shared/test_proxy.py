"""Tests for the MCP proxy pattern."""

from collections.abc import Callable
from typing import Any

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared.message import SessionMessage
from mcp.shared.proxy import mcp_proxy
from mcp.types import JSONRPCMessage, JSONRPCRequest

# Type aliases for clarity
ReadStream = MemoryObjectReceiveStream[SessionMessage | Exception]
WriteStream = MemoryObjectSendStream[SessionMessage]
StreamPair = tuple[ReadStream, WriteStream]
WriterReaderPair = tuple[MemoryObjectSendStream[SessionMessage | Exception], MemoryObjectReceiveStream[SessionMessage]]
StreamsFixtureReturn = tuple[StreamPair, StreamPair, WriterReaderPair, WriterReaderPair]


@pytest.fixture
async def create_streams() -> Callable[[], StreamsFixtureReturn]:
    """Helper fixture to create memory streams for testing with proper cleanup."""
    streams_to_cleanup: list[Any] = []

    def _create() -> StreamsFixtureReturn:
        client_read_writer, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        client_write, client_write_reader = anyio.create_memory_object_stream[SessionMessage](10)

        server_read_writer, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        server_write, server_write_reader = anyio.create_memory_object_stream[SessionMessage](10)

        # Track ALL 8 streams for cleanup (both send and receive ends of all 4 pairs)
        streams_to_cleanup.extend(
            [
                client_read_writer,
                client_read,
                client_write,
                client_write_reader,
                server_read_writer,
                server_read,
                server_write,
                server_write_reader,
            ]
        )

        return (
            (client_read, client_write),
            (server_read, server_write),
            (client_read_writer, client_write_reader),
            (server_read_writer, server_write_reader),
        )

    yield _create

    # Clean up any unclosed streams after the test
    for stream in streams_to_cleanup:
        try:
            await stream.aclose()
        except Exception:
            pass  # Already closed


@pytest.mark.anyio
async def test_proxy_forwards_client_to_server(create_streams):
    """Test that messages from client are forwarded to server."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        # Create a test message
        request = JSONRPCRequest(jsonrpc="2.0", id="1", method="test_method", params={"key": "value"})
        message = SessionMessage(JSONRPCMessage(request))

        async with mcp_proxy(client_streams, server_streams):
            # Send message from client
            await client_read_writer.send(message)

            # Verify it arrives at server
            with anyio.fail_after(1):
                received = await server_write_reader.receive()
                assert received.message.root.id == "1"
                assert received.message.root.method == "test_method"
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_forwards_server_to_client(create_streams):
    """Test that messages from server are forwarded to client."""
    client_streams, server_streams, (_, client_write_reader), (server_read_writer, _) = create_streams()

    try:
        # Create a test message
        request = JSONRPCRequest(jsonrpc="2.0", id="2", method="server_method", params={"data": "test"})
        message = SessionMessage(JSONRPCMessage(request))

        async with mcp_proxy(client_streams, server_streams):
            # Send message from server
            await server_read_writer.send(message)

            # Verify it arrives at client
            with anyio.fail_after(1):
                received = await client_write_reader.receive()
                assert received.message.root.id == "2"
                assert received.message.root.method == "server_method"
    finally:
        # Clean up test streams
        await server_read_writer.aclose()
        await client_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_bidirectional_forwarding(create_streams):
    """Test that proxy forwards messages in both directions simultaneously."""
    (
        client_streams,
        server_streams,
        (client_read_writer, client_write_reader),
        (
            server_read_writer,
            server_write_reader,
        ),
    ) = create_streams()

    # Unpack the streams passed to proxy for cleanup
    client_read, client_write = client_streams
    server_read, server_write = server_streams

    try:
        # Create test messages
        client_request = JSONRPCRequest(jsonrpc="2.0", id="client_1", method="client_method", params={})
        server_request = JSONRPCRequest(jsonrpc="2.0", id="server_1", method="server_method", params={})

        client_msg = SessionMessage(JSONRPCMessage(client_request))
        server_msg = SessionMessage(JSONRPCMessage(server_request))

        async with mcp_proxy(client_streams, server_streams):
            # Send messages from both sides
            await client_read_writer.send(client_msg)
            await server_read_writer.send(server_msg)

            # Verify both arrive at their destinations
            with anyio.fail_after(1):
                # Client message should arrive at server
                received_at_server = await server_write_reader.receive()
                assert received_at_server.message.root.id == "client_1"

                # Server message should arrive at client
                received_at_client = await client_write_reader.receive()
                assert received_at_client.message.root.id == "server_1"
    finally:
        # Clean up ALL 8 streams
        await client_read_writer.aclose()
        await client_write_reader.aclose()
        await server_read_writer.aclose()
        await server_write_reader.aclose()
        await client_read.aclose()
        await client_write.aclose()
        await server_read.aclose()
        await server_write.aclose()


@pytest.mark.anyio
async def test_proxy_error_handling(create_streams):
    """Test that errors are caught and onerror callback is invoked."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        errors = []

        def error_handler(error: Exception) -> None:
            """Collect errors."""
            errors.append(error)

        # Send an exception through the stream
        test_exception = ValueError("Test error")

        async with mcp_proxy(client_streams, server_streams, onerror=error_handler):
            await client_read_writer.send(test_exception)

            # Give it time to process
            await anyio.sleep(0.1)

            # Error should have been caught
            assert len(errors) == 1
            assert isinstance(errors[0], ValueError)
            assert str(errors[0]) == "Test error"
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_async_error_handler(create_streams):
    """Test that async error handlers work."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        errors = []

        async def async_error_handler(error: Exception) -> None:
            """Collect errors asynchronously."""
            await anyio.sleep(0.01)  # Simulate async work
            errors.append(error)

        test_exception = ValueError("Async test error")

        async with mcp_proxy(client_streams, server_streams, onerror=async_error_handler):
            await client_read_writer.send(test_exception)

            # Give it time to process
            await anyio.sleep(0.1)

            # Error should have been caught
            assert len(errors) == 1
            assert isinstance(errors[0], ValueError)
            assert str(errors[0]) == "Async test error"
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_continues_after_error(create_streams):
    """Test that proxy continues forwarding after an error."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        errors = []

        def error_handler(error: Exception) -> None:
            errors.append(error)

        async with mcp_proxy(client_streams, server_streams, onerror=error_handler):
            # Send an exception
            await client_read_writer.send(ValueError("Error 1"))

            # Send a valid message
            request = JSONRPCRequest(jsonrpc="2.0", id="after_error", method="test", params={})
            message = SessionMessage(JSONRPCMessage(request))
            await client_read_writer.send(message)

            # Valid message should still be forwarded
            with anyio.fail_after(1):
                received = await server_write_reader.receive()
                assert received.message.root.id == "after_error"

            # Error should have been captured
            assert len(errors) == 1
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_cleans_up_streams(create_streams):
    """Test that proxy exits cleanly and doesn't interfere with stream lifecycle."""
    (
        client_streams,
        server_streams,
        (client_read_writer, client_write_reader),
        (
            server_read_writer,
            server_write_reader,
        ),
    ) = create_streams()

    try:
        # Proxy should exit cleanly without raising exceptions
        async with mcp_proxy(client_streams, server_streams):
            pass  # Exit immediately

        # The proxy has exited cleanly. The streams are owned by the caller
        # (transport context managers in real usage), and can be closed normally.
    finally:
        # Verify streams can be closed normally (proxy doesn't prevent cleanup)
        await client_read_writer.aclose()
        await client_write_reader.aclose()
        await server_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_multiple_messages(create_streams):
    """Test that proxy can forward multiple messages."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        async with mcp_proxy(client_streams, server_streams):
            # Send multiple messages
            for i in range(5):
                request = JSONRPCRequest(jsonrpc="2.0", id=str(i), method=f"method_{i}", params={})
                message = SessionMessage(JSONRPCMessage(request))
                await client_read_writer.send(message)

            # Verify all messages arrive in order
            with anyio.fail_after(1):
                for i in range(5):
                    received = await server_write_reader.receive()
                    assert received.message.root.id == str(i)
                    assert received.message.root.method == f"method_{i}"
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_handles_closed_resource_error(create_streams):
    """Test that proxy handles ClosedResourceError gracefully."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        errors = []

        def error_handler(error: Exception) -> None:
            errors.append(error)

        async with mcp_proxy(client_streams, server_streams, onerror=error_handler):
            # Close the read stream to trigger ClosedResourceError
            client_read, _ = client_streams
            await client_read.aclose()

            # Give it time to process the closure
            await anyio.sleep(0.1)

            # Proxy should handle this gracefully without crashing
            # The ClosedResourceError is caught and logged, but not passed to onerror
            # (it's expected during shutdown)
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_closes_other_stream_on_close(create_streams):
    """Test that when one stream closes, the other is also closed."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with mcp_proxy(client_streams, server_streams):
            # Close the client read stream
            await client_read.aclose()

            # Give it time to process
            await anyio.sleep(0.1)

            # Server write stream should be closed
            # (we can't directly check if it's closed, but we can verify
            # that sending to it fails with ClosedResourceError)
            with pytest.raises(anyio.ClosedResourceError):
                request = JSONRPCRequest(jsonrpc="2.0", id="test", method="test", params={})
                message = SessionMessage(JSONRPCMessage(request))
                await server_write.send(message)
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_error_in_callback(create_streams):
    """Test that errors in the error callback are handled gracefully."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        def failing_error_handler(error: Exception) -> None:
            """Error handler that raises an exception."""
            raise RuntimeError("Callback error")

        # Send an exception through the stream
        test_exception = ValueError("Test error")

        async with mcp_proxy(client_streams, server_streams, onerror=failing_error_handler):
            await client_read_writer.send(test_exception)

            # Give it time to process
            await anyio.sleep(0.1)

            # Proxy should continue working despite callback error
            request = JSONRPCRequest(jsonrpc="2.0", id="after_callback_error", method="test", params={})
            message = SessionMessage(JSONRPCMessage(request))
            await client_read_writer.send(message)

            # Valid message should still be forwarded
            with anyio.fail_after(1):
                received = await server_write_reader.receive()
                assert received.message.root.id == "after_callback_error"
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()


@pytest.mark.anyio
async def test_proxy_async_error_in_callback(create_streams):
    """Test that async errors in the error callback are handled gracefully."""
    client_streams, server_streams, (client_read_writer, _), (_, server_write_reader) = create_streams()

    try:
        async def failing_async_error_handler(error: Exception) -> None:
            """Async error handler that raises an exception."""
            await anyio.sleep(0.01)
            raise RuntimeError("Async callback error")

        # Send an exception through the stream
        test_exception = ValueError("Test error")

        async with mcp_proxy(client_streams, server_streams, onerror=failing_async_error_handler):
            await client_read_writer.send(test_exception)

            # Give it time to process
            await anyio.sleep(0.1)

            # Proxy should continue working despite callback error
            request = JSONRPCRequest(jsonrpc="2.0", id="after_async_callback_error", method="test", params={})
            message = SessionMessage(JSONRPCMessage(request))
            await client_read_writer.send(message)

            # Valid message should still be forwarded
            with anyio.fail_after(1):
                received = await server_write_reader.receive()
                assert received.message.root.id == "after_async_callback_error"
    finally:
        # Clean up test streams
        await client_read_writer.aclose()
        await server_write_reader.aclose()
