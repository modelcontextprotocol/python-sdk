"""Stream protocols for MCP transports.

These are general-purpose protocols satisfied by both ``MemoryObjectSendStream``/
``MemoryObjectReceiveStream`` and the context-aware wrappers in ``_context_streams``.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, TypeVar

from typing_extensions import Self

T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)


class ReadStream(Protocol[T_co]):
    """Protocol for reading items from a stream.

    Consumers that need the sender's context should use
    ``getattr(stream, 'last_context', None)``.
    """

    async def receive(self) -> T_co: ...
    async def aclose(self) -> None: ...
    def __aiter__(self) -> ReadStream[T_co]: ...
    async def __anext__(self) -> T_co: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...


class WriteStream(Protocol[T_contra]):
    """Protocol for writing items to a stream."""

    async def send(self, item: T_contra, /) -> None: ...
    async def aclose(self) -> None: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...
