"""Context-aware memory stream wrappers.

anyio memory streams do not propagate ``contextvars.Context`` across task
boundaries.  These thin wrappers capture the sender's context at ``send()``
time and expose it on the receive side via ``last_context``, so consumers
can restore it with ``ctx.run(handler, item)``.

The iteration interface is unchanged (yields ``T``, not tuples), keeping
these wrappers duck-type compatible with plain ``MemoryObjectSendStream``
and ``MemoryObjectReceiveStream``.
"""

from __future__ import annotations

import contextvars
from types import TracebackType
from typing import Any, Generic, TypeVar

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

T = TypeVar("T")

# Internal payload carried through the underlying raw stream.
_Envelope = tuple[contextvars.Context, T]


class ContextSendStream(Generic[T]):
    """Send-side wrapper that snapshots ``contextvars.copy_context()`` on every ``send()``."""

    __slots__ = ("_inner",)

    def __init__(self, inner: MemoryObjectSendStream[_Envelope[T]]) -> None:
        self._inner = inner

    async def send(self, item: T) -> None:
        await self._inner.send((contextvars.copy_context(), item))

    async def send_with_context(self, context: contextvars.Context, item: T) -> None:
        await self._inner.send((context, item))

    def close(self) -> None:
        self._inner.close()

    async def aclose(self) -> None:
        await self._inner.aclose()

    def clone(self) -> ContextSendStream[T]:  # pragma: no cover
        return ContextSendStream(self._inner.clone())

    async def __aenter__(self) -> ContextSendStream[T]:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


class ContextReceiveStream(Generic[T]):
    """Receive-side wrapper that yields ``T`` and stores the sender's context in ``last_context``."""

    __slots__ = ("_inner", "last_context")

    def __init__(self, inner: MemoryObjectReceiveStream[_Envelope[T]]) -> None:
        self._inner = inner
        self.last_context: contextvars.Context | None = None

    async def receive(self) -> T:
        ctx, item = await self._inner.receive()
        self.last_context = ctx
        return item

    def close(self) -> None:
        self._inner.close()

    async def aclose(self) -> None:
        await self._inner.aclose()

    def clone(self) -> ContextReceiveStream[T]:  # pragma: no cover
        return ContextReceiveStream(self._inner.clone())

    def __aiter__(self) -> ContextReceiveStream[T]:
        return self

    async def __anext__(self) -> T:
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration

    async def __aenter__(self) -> ContextReceiveStream[T]:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.aclose()
        return None


class create_context_streams(
    tuple[ContextSendStream[T], ContextReceiveStream[T]],
):
    """Create context-aware memory object streams.

    Supports ``create_context_streams[T](n)`` bracket syntax,
    matching anyio's ``create_memory_object_stream`` API style.
    """

    def __new__(cls, max_buffer_size: float = 0) -> tuple[ContextSendStream[T], ContextReceiveStream[T]]:  # type: ignore[type-var]
        raw_send: MemoryObjectSendStream[Any]
        raw_receive: MemoryObjectReceiveStream[Any]
        raw_send, raw_receive = anyio.create_memory_object_stream(max_buffer_size)
        return (ContextSendStream(raw_send), ContextReceiveStream(raw_receive))
