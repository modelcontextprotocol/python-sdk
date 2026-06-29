"""Shared helpers for the interaction suite.

Keep this small: client-callback typing aliases and the recording transport only. Server fixtures
and assertion helpers belong in the test that uses them.
"""

from types import TracebackType

import anyio
from mcp_types import ClientResult, ServerNotification, ServerRequest
from typing_extensions import Self

from mcp.client._transport import ReadStream, Transport, TransportStreams, WriteStream
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder

# TODO: delete once the SDK exports a named alias for MessageHandlerFnT's parameter union (cf. ClientRequestContext).
IncomingMessage = RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception
"""Everything a client message handler can receive."""


class _RecordingReadStream:
    """Delegates to a read stream, appending every received message to a log."""

    def __init__(self, inner: ReadStream[SessionMessage | Exception], log: list[SessionMessage | Exception]) -> None:
        self._inner = inner
        self._log = log

    async def receive(self) -> SessionMessage | Exception:
        item = await self._inner.receive()
        self._log.append(item)
        return item

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> bool | None:
        await self.aclose()
        return None


class _RecordingWriteStream:
    """Delegates to a write stream, appending every sent message to a log."""

    def __init__(self, inner: WriteStream[SessionMessage], log: list[SessionMessage]) -> None:
        self._inner = inner
        self._log = log

    async def send(self, item: SessionMessage, /) -> None:
        # Record only after the inner send returns: a failed or cancelled send never reached the transport.
        await self._inner.send(item)
        self._log.append(item)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> bool | None:
        await self.aclose()
        return None


class RecordingTransport:
    """Wraps a Transport, logging client writes to `sent` and server deliveries to `received`.

    Recording sits at the transport seam, never the session, so wire-level assertions survive
    changes to the receive path.
    """

    def __init__(self, inner: Transport) -> None:
        self.inner = inner
        self.sent: list[SessionMessage] = []
        self.received: list[SessionMessage | Exception] = []

    async def __aenter__(self) -> TransportStreams:
        read_stream, write_stream = await self.inner.__aenter__()
        return _RecordingReadStream(read_stream, self.received), _RecordingWriteStream(write_stream, self.sent)

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> bool | None:
        return await self.inner.__aexit__(exc_type, exc_val, exc_tb)
