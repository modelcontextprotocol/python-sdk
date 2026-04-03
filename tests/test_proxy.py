from __future__ import annotations

from types import TracebackType

import anyio
import pytest

from mcp.proxy import mcp_proxy
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCRequest


def make_message(request_id: str, method: str) -> SessionMessage:
    return SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params={}))


def assert_request(message: SessionMessage, request_id: str, method: str) -> None:
    assert isinstance(message.message, JSONRPCRequest)
    assert message.message.id == request_id
    assert message.message.method == method


class StaticReadStream:
    def __init__(self, *items: SessionMessage | Exception, error: Exception | None = None) -> None:
        self._items = list(items)
        self._error = error
        self.closed = False

    async def receive(self) -> SessionMessage | Exception:
        try:
            return await self.__anext__()
        except StopAsyncIteration as exc:
            raise anyio.EndOfStream from exc

    async def aclose(self) -> None:
        self.closed = True

    def __aiter__(self) -> StaticReadStream:
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        if self._items:
            return self._items.pop(0)
        if self._error is not None:
            error = self._error
            self._error = None
            raise error
        raise StopAsyncIteration

    async def __aenter__(self) -> StaticReadStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


class TrackingWriteStream:
    def __init__(self, error: Exception | None = None) -> None:
        self.items: list[SessionMessage] = []
        self.error = error
        self.closed = anyio.Event()

    async def send(self, item: SessionMessage, /) -> None:
        if self.error is not None:
            raise self.error
        self.items.append(item)

    async def aclose(self) -> None:
        self.closed.set()

    async def __aenter__(self) -> TrackingWriteStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


@pytest.mark.anyio
async def test_proxy_forwards_messages_bidirectionally() -> None:
    client_read_send, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_write, client_write_read = anyio.create_memory_object_stream[SessionMessage](1)
    server_read_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    server_write, server_write_read = anyio.create_memory_object_stream[SessionMessage](1)

    async with (
        client_read_send,
        client_read,
        client_write,
        client_write_read,
        server_read_send,
        server_read,
        server_write,
        server_write_read,
    ):
        async with mcp_proxy((client_read, client_write), (server_read, server_write)):
            await client_read_send.send(make_message("client", "client/method"))
            await server_read_send.send(make_message("server", "server/method"))

            assert_request(await server_write_read.receive(), "client", "client/method")
            assert_request(await client_write_read.receive(), "server", "server/method")


@pytest.mark.anyio
async def test_proxy_calls_sync_error_handler_and_continues() -> None:
    errors: list[Exception] = []
    handled = anyio.Event()

    def on_error(error: Exception) -> None:
        errors.append(error)
        handled.set()

    client_read_send, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_write, _client_write_read = anyio.create_memory_object_stream[SessionMessage](1)
    server_read_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    server_write, server_write_read = anyio.create_memory_object_stream[SessionMessage](1)

    async with (
        client_read_send,
        client_read,
        client_write,
        _client_write_read,
        server_read_send,
        server_read,
        server_write,
        server_write_read,
    ):
        async with mcp_proxy((client_read, client_write), (server_read, server_write), on_error=on_error):
            await client_read_send.send(ValueError("boom"))
            await handled.wait()
            await client_read_send.send(make_message("after-error", "client/method"))

            assert len(errors) == 1
            assert isinstance(errors[0], ValueError)
            assert str(errors[0]) == "boom"
            assert_request(await server_write_read.receive(), "after-error", "client/method")


@pytest.mark.anyio
async def test_proxy_calls_async_error_handler() -> None:
    errors: list[Exception] = []
    handled = anyio.Event()

    async def on_error(error: Exception) -> None:
        errors.append(error)
        handled.set()

    client_read_send, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_write, _client_write_read = anyio.create_memory_object_stream[SessionMessage](1)
    server_read_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    server_write, _server_write_read = anyio.create_memory_object_stream[SessionMessage](1)

    async with (
        client_read_send,
        client_read,
        client_write,
        _client_write_read,
        server_read_send,
        server_read,
        server_write,
        _server_write_read,
    ):
        async with mcp_proxy((client_read, client_write), (server_read, server_write), on_error=on_error):
            await client_read_send.send(ValueError("async-boom"))
            await handled.wait()

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "async-boom"


@pytest.mark.anyio
async def test_proxy_ignores_sync_error_handler_failures() -> None:
    def on_error(error: Exception) -> None:
        raise RuntimeError(f"handler failed for {error}")

    client_read_send, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_write, _client_write_read = anyio.create_memory_object_stream[SessionMessage](1)
    server_read_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    server_write, server_write_read = anyio.create_memory_object_stream[SessionMessage](1)

    async with (
        client_read_send,
        client_read,
        client_write,
        _client_write_read,
        server_read_send,
        server_read,
        server_write,
        server_write_read,
    ):
        async with mcp_proxy((client_read, client_write), (server_read, server_write), on_error=on_error):
            await client_read_send.send(ValueError("boom"))
            await client_read_send.send(make_message("after-sync-handler-error", "client/method"))
            assert_request(await server_write_read.receive(), "after-sync-handler-error", "client/method")


@pytest.mark.anyio
async def test_proxy_ignores_async_error_handler_failures() -> None:
    async def on_error(error: Exception) -> None:
        raise RuntimeError(f"handler failed for {error}")

    client_read_send, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_write, _client_write_read = anyio.create_memory_object_stream[SessionMessage](1)
    server_read_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    server_write, server_write_read = anyio.create_memory_object_stream[SessionMessage](1)

    async with (
        client_read_send,
        client_read,
        client_write,
        _client_write_read,
        server_read_send,
        server_read,
        server_write,
        server_write_read,
    ):
        async with mcp_proxy((client_read, client_write), (server_read, server_write), on_error=on_error):
            await client_read_send.send(ValueError("boom"))
            await client_read_send.send(make_message("after-async-handler-error", "client/method"))
            assert_request(await server_write_read.receive(), "after-async-handler-error", "client/method")


@pytest.mark.anyio
async def test_proxy_continues_without_error_handler() -> None:
    client_read_send, client_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client_write, _client_write_read = anyio.create_memory_object_stream[SessionMessage](1)
    server_read_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    server_write, server_write_read = anyio.create_memory_object_stream[SessionMessage](1)

    async with (
        client_read_send,
        client_read,
        client_write,
        _client_write_read,
        server_read_send,
        server_read,
        server_write,
        server_write_read,
    ):
        async with mcp_proxy((client_read, client_write), (server_read, server_write)):
            await client_read_send.send(ValueError("boom"))
            await client_read_send.send(make_message("after-no-handler", "client/method"))
            assert_request(await server_write_read.receive(), "after-no-handler", "client/method")


@pytest.mark.anyio
async def test_proxy_stops_forwarding_when_target_stream_is_closed() -> None:
    server_write = TrackingWriteStream(anyio.ClosedResourceError())
    client_write = TrackingWriteStream()

    async with mcp_proxy(
        (StaticReadStream(make_message("client", "client/method")), server_write),
        (StaticReadStream(), client_write),
    ):
        await server_write.closed.wait()

    assert server_write.items == []
    assert server_write.closed.is_set()
    assert client_write.closed.is_set()


@pytest.mark.anyio
async def test_proxy_closes_target_stream_when_source_stream_is_closed() -> None:
    server_write = TrackingWriteStream()
    client_write = TrackingWriteStream()

    async with mcp_proxy((StaticReadStream(), server_write), (StaticReadStream(), client_write)):
        await server_write.closed.wait()
        await client_write.closed.wait()

    assert server_write.items == []
    assert client_write.items == []


@pytest.mark.anyio
async def test_proxy_handles_closed_resource_error_from_source_stream() -> None:
    server_write = TrackingWriteStream()
    client_write = TrackingWriteStream()

    async with mcp_proxy(
        (StaticReadStream(error=anyio.ClosedResourceError()), server_write),
        (StaticReadStream(), client_write),
    ):
        await server_write.closed.wait()

    assert server_write.items == []
