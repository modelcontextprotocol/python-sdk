"""Task group wrapper that collapses single-exception ExceptionGroups.

When an anyio task group contains tasks and one fails, the exception is
always wrapped in an ExceptionGroup — even if there is only one real
exception. This makes it impossible for callers to catch specific error
types with ``except SomeError:``.

This module provides a drop-in replacement for ``anyio.create_task_group()``
that automatically unwraps single-exception groups so callers receive the
original exception directly.
"""

from __future__ import annotations

import sys
from types import TracebackType

import anyio
from anyio.abc import TaskGroup

if sys.version_info < (3, 11):  # pragma: no cover
    from exceptiongroup import BaseExceptionGroup


def collapse_exception_group(exc: BaseExceptionGroup) -> BaseException:  # type: ignore[type-arg]
    """Unwrap nested single-exception BaseExceptionGroups.

    If the group (and any nested groups) each contain exactly one exception,
    return the innermost real exception.  Otherwise return *exc* unchanged.
    """
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:  # type: ignore[reportUnnecessaryIsInstance]
        exc = exc.exceptions[0]  # type: ignore[assignment]
    return exc


class _CollapsingTaskGroup:
    """A thin wrapper around an anyio ``TaskGroup`` that collapses exceptions.

    On ``__aexit__``, if the task group raises a ``BaseExceptionGroup`` that
    contains only a single exception, that inner exception is re-raised
    directly so callers can ``except`` it by its concrete type.

    The wrapper delegates ``start_soon``, ``start``, and ``cancel_scope`` to
    the underlying task group.
    """

    def __init__(self) -> None:
        self._task_group: TaskGroup | None = None

    def _tg(self) -> TaskGroup:
        if self._task_group is None:
            raise RuntimeError("Task group has not been entered")
        return self._task_group

    @property
    def cancel_scope(self) -> anyio.CancelScope:
        return self._tg().cancel_scope

    def start_soon(self, *args: object, **kwargs: object) -> None:
        self._tg().start_soon(*args, **kwargs)  # type: ignore[arg-type]

    async def start(self, *args: object, **kwargs: object) -> object:
        return await self._tg().start(*args, **kwargs)  # type: ignore[arg-type]

    async def __aenter__(self) -> _CollapsingTaskGroup:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        try:
            return await self._tg().__aexit__(exc_type, exc_val, exc_tb)
        except BaseExceptionGroup as eg:
            collapsed = collapse_exception_group(eg)
            if collapsed is not eg:
                raise collapsed from eg
            raise


def create_mcp_task_group() -> _CollapsingTaskGroup:
    """Create an anyio task group that collapses single-exception groups.

    Use this as a drop-in replacement for ``anyio.create_task_group()``::

        async with create_mcp_task_group() as tg:
            tg.start_soon(some_task)
    """
    return _CollapsingTaskGroup()
