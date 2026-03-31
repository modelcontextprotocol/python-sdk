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


# coverage branch tracking reports missing arcs on Protocol stub methods
# (def -> exit) because they are never called at runtime.
class ReadStream(Protocol[T_co]):  # pragma: no branch
    """Protocol for reading items from a stream.

    Consumers that need the sender's context should use
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


class WriteStream(Protocol[T_contra]):  # pragma: no branch
    """Protocol for writing items to a stream."""

    async def send(self, item: T_contra, /) -> None: ...  # pragma: no branch
    async def aclose(self) -> None: ...  # pragma: no branch
    async def __aenter__(self) -> Self: ...  # pragma: no branch
    async def __aexit__(  # pragma: no branch
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...
