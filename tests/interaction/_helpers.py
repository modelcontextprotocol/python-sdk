"""Shared helpers for the interaction suite.

Keep this module small: it holds the recording transport used by the wire-level tests and the
`tool_listing` handler factory. Servers and assertion helpers belong in the test that uses them.
"""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

import anyio
from mcp_types import ListToolsResult, PaginatedRequestParams, Tool
from typing_extensions import Self

from mcp.client._transport import ReadStream, Transport, TransportStreams, WriteStream
from mcp.server import ServerRequestContext
from mcp.shared.message import SessionMessage


def tool_listing(
    *tools: Tool | str,
) -> Callable[[ServerRequestContext[Any, Any], PaginatedRequestParams | None], Awaitable[ListToolsResult]]:
    """An `on_list_tools` handler advertising `tools`; a bare name becomes an argument-less tool.

    `Client.call_tool` lists tools once per connection to learn their output schemas, so a server
    whose tools are called needs a tools/list handler even when the test never lists.
    """
    listed = [Tool(name=t, input_schema={"type": "object"}) if isinstance(t, str) else t for t in tools]

    async def list_tools(ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=listed)

    return list_tools


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
    """Wraps a Transport and records every message crossing the client's transport boundary.

    `sent` holds everything the client wrote towards the server; `received` holds everything the
    server delivered to the client. The recording sits at the transport seam -- the exact payloads
    a real transport would serialise -- and never touches the session, so wire-level assertions
    written against it survive changes to the receive path.
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
