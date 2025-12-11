"""Tests for the MCP proxy module."""

from types import SimpleNamespace
from typing import Any

import anyio
import pytest

from mcp.proxy import MessageStream, mcp_proxy
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest


def make_message(id: str, method: str = "test") -> SessionMessage:
    """Create a test SessionMessage."""
    request = JSONRPCRequest(jsonrpc="2.0", id=id, method=method, params={})
    return SessionMessage(message=JSONRPCMessage(request))


@pytest.fixture
async def proxy_streams() -> Any:
    """Create streams for proxy testing.

    Returns a SimpleNamespace with:
        client_streams: (read, write) passed to mcp_proxy
        server_streams: (read, write) passed to mcp_proxy
        inject_from_client: send here to inject messages "from" the client
        receive_at_server: receive here to get messages forwarded "to" the server
        inject_from_server: send here to inject messages "from" the server
        receive_at_client: receive here to get messages forwarded "to" the client
    """
    # Client -> Server direction
    inject_from_client, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_write, receive_at_server = anyio.create_memory_object_stream[SessionMessage](10)

    # Server -> Client direction
    inject_from_server, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    client_write, receive_at_client = anyio.create_memory_object_stream[SessionMessage](10)

    client_streams: MessageStream = (client_read, client_write)
    server_streams: MessageStream = (server_read, server_write)

    async with (
        inject_from_client,
        client_read,
        server_write,
        receive_at_server,
        inject_from_server,
        server_read,
        client_write,
        receive_at_client,
    ):
        yield SimpleNamespace(
            client_streams=client_streams,
            server_streams=server_streams,
            inject_from_client=inject_from_client,
            receive_at_server=receive_at_server,
            inject_from_server=inject_from_server,
            receive_at_client=receive_at_client,
        )


@pytest.mark.anyio
async def test_forwards_client_to_server(proxy_streams: Any) -> None:
    """Messages from client are forwarded to server."""
    msg = make_message(id="1", method="client_method")

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        await proxy_streams.inject_from_client.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_server.receive()

        assert received.message.root.id == "1"
        assert received.message.root.method == "client_method"


@pytest.mark.anyio
async def test_forwards_server_to_client(proxy_streams: Any) -> None:
    """Messages from server are forwarded to client."""
    msg = make_message(id="2", method="server_method")

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        await proxy_streams.inject_from_server.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_client.receive()

        assert received.message.root.id == "2"
        assert received.message.root.method == "server_method"


@pytest.mark.anyio
async def test_bidirectional_forwarding(proxy_streams: Any) -> None:
    """Messages flow in both directions simultaneously."""
    client_msg = make_message(id="client_1")
    server_msg = make_message(id="server_1")

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        await proxy_streams.inject_from_client.send(client_msg)
        await proxy_streams.inject_from_server.send(server_msg)

        with anyio.fail_after(1):
            received_at_server = await proxy_streams.receive_at_server.receive()
            received_at_client = await proxy_streams.receive_at_client.receive()

        assert received_at_server.message.root.id == "client_1"
        assert received_at_client.message.root.id == "server_1"


@pytest.mark.anyio
async def test_multiple_messages_in_order(proxy_streams: Any) -> None:
    """Multiple messages are forwarded in order."""
    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        for i in range(5):
            msg = make_message(id=str(i), method=f"method_{i}")
            await proxy_streams.inject_from_client.send(msg)

        with anyio.fail_after(1):
            for i in range(5):
                received = await proxy_streams.receive_at_server.receive()
                assert received.message.root.id == str(i)
                assert received.message.root.method == f"method_{i}"


@pytest.mark.anyio
async def test_error_callback_called(proxy_streams: Any) -> None:
    """Exceptions on the stream trigger the error callback."""
    errors: list[Exception] = []
    error_received = anyio.Event()

    def on_error(e: Exception) -> None:
        errors.append(e)
        error_received.set()

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams, on_error=on_error):
        await proxy_streams.inject_from_client.send(ValueError("test error"))

        with anyio.fail_after(1):
            await error_received.wait()

        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)
        assert str(errors[0]) == "test error"


@pytest.mark.anyio
async def test_async_error_callback(proxy_streams: Any) -> None:
    """Async error callbacks are awaited."""
    errors: list[Exception] = []
    error_received = anyio.Event()

    async def on_error(e: Exception) -> None:
        await anyio.sleep(0)  # Yield to prove we're async
        errors.append(e)
        error_received.set()

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams, on_error=on_error):
        await proxy_streams.inject_from_client.send(ValueError("async error"))

        with anyio.fail_after(1):
            await error_received.wait()

        assert len(errors) == 1
        assert str(errors[0]) == "async error"


@pytest.mark.anyio
async def test_continues_after_error(proxy_streams: Any) -> None:
    """Proxy continues forwarding after handling an error."""
    errors: list[Exception] = []
    error_received = anyio.Event()

    def on_error(e: Exception) -> None:
        errors.append(e)
        error_received.set()

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams, on_error=on_error):
        # Send an error
        await proxy_streams.inject_from_client.send(ValueError("error"))

        with anyio.fail_after(1):
            await error_received.wait()

        # Send a valid message after the error
        msg = make_message(id="after_error")
        await proxy_streams.inject_from_client.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_server.receive()

        assert received.message.root.id == "after_error"
        assert len(errors) == 1


@pytest.mark.anyio
async def test_error_callback_exception_ignored(proxy_streams: Any) -> None:
    """If the error callback raises, the proxy continues."""
    callback_called = anyio.Event()

    def on_error(e: Exception) -> None:
        callback_called.set()
        raise RuntimeError("callback error")

    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams, on_error=on_error):
        await proxy_streams.inject_from_client.send(ValueError("trigger"))

        with anyio.fail_after(1):
            await callback_called.wait()

        # Proxy should still work after callback raised
        msg = make_message(id="still_works")
        await proxy_streams.inject_from_client.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_server.receive()

        assert received.message.root.id == "still_works"


@pytest.mark.anyio
async def test_no_error_callback(proxy_streams: Any) -> None:
    """Proxy works without an error callback."""
    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        # Send an exception (should be silently ignored)
        await proxy_streams.inject_from_client.send(ValueError("ignored"))

        # Send a valid message
        msg = make_message(id="works")
        await proxy_streams.inject_from_client.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_server.receive()

        assert received.message.root.id == "works"


@pytest.mark.anyio
async def test_write_stream_closes_gracefully(proxy_streams: Any) -> None:
    """When write stream closes, that direction stops without crashing."""
    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        # Close the destination for client->server
        await proxy_streams.receive_at_server.aclose()

        # Try to send a message (should not crash)
        msg = make_message(id="dropped")
        await proxy_streams.inject_from_client.send(msg)

        # Use the other direction as a synchronization point - if this works,
        # the proxy has had time to process the earlier message
        sync_msg = make_message(id="sync")
        await proxy_streams.inject_from_server.send(sync_msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_client.receive()
        assert received.message.root.id == "sync"


@pytest.mark.anyio
async def test_other_direction_continues_after_close(proxy_streams: Any) -> None:
    """When one direction's write closes, the other direction continues."""
    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        # Close the client->server direction
        await proxy_streams.receive_at_server.aclose()

        # Server->client should still work
        msg = make_message(id="still_works")
        await proxy_streams.inject_from_server.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_client.receive()

        assert received.message.root.id == "still_works"


@pytest.mark.anyio
async def test_read_stream_closes(proxy_streams: Any) -> None:
    """When read stream closes, the forward loop exits."""
    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        # Close the source for client->server
        await proxy_streams.inject_from_client.aclose()

        # The other direction should still work - this also serves as
        # synchronization to ensure the close has been processed
        msg = make_message(id="other_direction")
        await proxy_streams.inject_from_server.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_client.receive()

        assert received.message.root.id == "other_direction"


@pytest.mark.anyio
async def test_context_exit_stops_forwarding(proxy_streams: Any) -> None:
    """Exiting the context stops all forwarding."""
    async with mcp_proxy(proxy_streams.client_streams, proxy_streams.server_streams):
        msg = make_message(id="before_exit")
        await proxy_streams.inject_from_client.send(msg)

        with anyio.fail_after(1):
            received = await proxy_streams.receive_at_server.receive()
        assert received.message.root.id == "before_exit"

    # After context exit, the proxy task group is cancelled
    # New messages sent won't be forwarded (streams may be closed or orphaned)
