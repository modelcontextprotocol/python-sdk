"""Transport protocol for MCP clients."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol, TypeVar, runtime_checkable

from typing_extensions import Self

from mcp.shared.message import SessionMessage

T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)


@runtime_checkable
class ReadStream(Protocol[T_co]):  # pragma: no branch
    """Protocol for reading items from a stream.

    Both ``MemoryObjectReceiveStream`` and ``ContextReceiveStream`` satisfy
    this protocol.  Consumers that need the sender's context should use
    ``getattr(stream, 'last_context', None)``.
    """

    async def receive(self) -> T_co: ...  # pragma: no branch
    async def aclose(self) -> None: ...  # pragma: no branch
    def __aiter__(self) -> ReadStream[T_co]: ...  # pragma: no branch
    async def __anext__(self) -> T_co: ...  # pragma: no branch
    async def __aenter__(self) -> Self: ...  # pragma: no branch
    async def __aexit__(  # pragma: no branch
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...


@runtime_checkable
class WriteStream(Protocol[T_contra]):  # pragma: no branch
    """Protocol for writing items to a stream.

    Both ``MemoryObjectSendStream`` and ``ContextSendStream`` satisfy
    this protocol.
    """

    async def send(self, item: T_contra, /) -> None: ...  # pragma: no branch
    async def aclose(self) -> None: ...  # pragma: no branch
    async def __aenter__(self) -> Self: ...  # pragma: no branch
    async def __aexit__(  # pragma: no branch
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...


TransportStreams = tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]


class Transport(AbstractAsyncContextManager[TransportStreams], Protocol):
    """Protocol for MCP transports.

    A transport is an async context manager that yields read and write streams
    for bidirectional communication with an MCP server.
    """
