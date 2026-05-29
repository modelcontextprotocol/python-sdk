"""Shared helpers for the interaction suite.

Keep this module small: it exists only for (a) types that every test would otherwise have to
assemble from the SDK's internals to annotate a client callback, and (b) the recording wrapper
used by the wire-level tests. Server fixtures and assertion helpers belong in the test that uses
them.
"""

from types import TracebackType

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from typing_extensions import Self

from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import ClientResult, ServerNotification, ServerRequest

# TODO: this union is the parameter type of every client message handler (MessageHandlerFnT),
# but the SDK does not export a name for it -- writing a correctly-typed handler requires
# importing RequestResponder from mcp.shared.session and assembling the union by hand. It
# should be a named, exported alias next to MessageHandlerFnT (like ClientRequestContext is
# for the request callbacks), at which point this alias can be deleted.
IncomingMessage = RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception
"""Everything a client message handler can receive."""

ReadStream = MemoryObjectReceiveStream[SessionMessage | Exception]
WriteStream = MemoryObjectSendStream[SessionMessage]
"""Local aliases for the v1 SDK's session-stream types (v1 has no exported `ReadStream`/
`WriteStream` names); exported so wire-level / scripted-peer tests can annotate without
reaching into anyio."""


class _RecordingReadStream:
    """Delegates to a read stream, appending every received message to a log."""

    def __init__(self, inner: ReadStream, log: list[SessionMessage | Exception]) -> None:
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

    def __init__(self, inner: WriteStream, log: list[SessionMessage]) -> None:
        self._inner = inner
        self._log = log

    async def send(self, item: SessionMessage, /) -> None:
        self._log.append(item)
        await self._inner.send(item)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> bool | None:
        await self.aclose()
        return None


class Recording:
    """Wraps a (read, write) stream pair and records every message crossing it.

    `sent` holds everything the client wrote towards the server; `received` holds everything the
    server delivered to the client. The recording sits at the transport seam -- the exact payloads
    a real transport would serialise -- and never touches the session, so wire-level assertions
    written against it survive changes to the receive path.

    v1 has no `Transport` abstraction; tests insert this between
    `create_client_server_memory_streams()` and `ClientSession`.
    """

    def __init__(self, read: ReadStream, write: WriteStream) -> None:
        self.sent: list[SessionMessage] = []
        self.received: list[SessionMessage | Exception] = []
        # Duck-typed stand-ins for the anyio stream classes; ClientSession only calls
        # .receive()/.send()/.aclose() so the runtime contract holds.
        self.read: ReadStream = _RecordingReadStream(read, self.received)  # type: ignore[assignment]
        self.write: WriteStream = _RecordingWriteStream(write, self.sent)  # type: ignore[assignment]
