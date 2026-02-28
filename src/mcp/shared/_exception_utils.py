"""Utilities for collapsing BaseExceptionGroup noise from anyio task groups.

When a task in an anyio task group fails, sibling tasks are cancelled.  The
resulting ``BaseExceptionGroup`` contains the real error alongside
``Cancelled`` exceptions from those siblings.  This module provides helpers
that detect that pattern and re-raise just the original error, preserving the
full group as ``__cause__`` for debugging.

If multiple tasks fail with non-cancellation errors concurrently, the full
``BaseExceptionGroup`` is preserved unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator

import anyio
import anyio.abc

if sys.version_info < (3, 11):  # pragma: no cover
    from exceptiongroup import BaseExceptionGroup


def collapse_exception_group(
    eg: BaseExceptionGroup,
    cancelled_type: type[BaseException] = asyncio.CancelledError,
) -> BaseException:
    """Extract the single real error from a *BaseExceptionGroup* if possible.

    Args:
        eg: The exception group to collapse.
        cancelled_type: The cancellation exception class to filter out.
            Defaults to ``asyncio.CancelledError``.  The ``open_task_group``
            context manager passes ``anyio.get_cancelled_exc_class()`` so the
            correct type is used for any backend.

    Returns:
        * The single non-cancelled exception if exactly one exists.
        * A filtered group (cancelled noise stripped) if multiple real errors.
        * A single ``Cancelled`` if all exceptions are cancellations.
    """

    # split(type) uses isinstance on leaf exceptions, NOT on the group.
    # Using split(lambda) is incorrect because the lambda would first be
    # called on the group object itself.
    cancelled, non_cancelled = eg.split(cancelled_type)

    if non_cancelled is None:
        # Every exception is a cancellation – surface just one.
        return eg.exceptions[0]

    if len(non_cancelled.exceptions) == 1:
        return non_cancelled.exceptions[0]

    # Multiple real errors – return the filtered group (without Cancelled).
    return non_cancelled if non_cancelled is not eg else eg


@contextlib.asynccontextmanager
async def open_task_group() -> AsyncIterator[anyio.abc.TaskGroup]:
    """Drop-in replacement for ``anyio.create_task_group()`` that collapses
    exception groups containing a single real error plus cancellation noise.

    Usage::

        async with open_task_group() as tg:
            tg.start_soon(some_task)
            ...

    If *some_task* raises ``ConnectionError`` and all siblings are cancelled,
    this context manager will raise ``ConnectionError`` directly (with the
    original ``BaseExceptionGroup`` attached as ``__cause__``).
    """

    try:
        async with anyio.create_task_group() as tg:
            yield tg
    except BaseExceptionGroup as eg:
        cancelled_cls = anyio.get_cancelled_exc_class()
        collapsed = collapse_exception_group(eg, cancelled_type=cancelled_cls)
        if collapsed is not eg:
            raise collapsed from eg
        raise  # pragma: lax no cover