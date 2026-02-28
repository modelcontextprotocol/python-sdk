"""Utilities for collapsing ExceptionGroups from anyio task group cancellations.

When a task group has one real failure and N cancelled siblings, anyio wraps them
all in a BaseExceptionGroup. This makes it hard for callers to classify the root
cause. These utilities extract the single real error when possible.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from anyio.abc import TaskGroup

if sys.version_info < (3, 11):  # pragma: lax no cover
    from exceptiongroup import BaseExceptionGroup  # pragma: lax no cover


def collapse_exception_group(exc_group: BaseExceptionGroup[BaseException]) -> BaseException:
    """Collapse a single-error exception group into the underlying exception.

    When a task in an anyio task group fails, sibling tasks are cancelled,
    producing ``Cancelled`` exceptions. The task group then wraps everything
    in a ``BaseExceptionGroup``. If there is exactly one non-cancellation
    error, this function returns it directly so callers can handle it without
    unwrapping.

    Args:
        exc_group: The exception group to collapse.

    Returns:
        The single non-cancellation exception if there is exactly one,
        otherwise the original exception group unchanged.
    """
    cancelled_class = anyio.get_cancelled_exc_class()
    real_errors: list[BaseException] = [exc for exc in exc_group.exceptions if not isinstance(exc, cancelled_class)]

    if len(real_errors) == 1:
        return real_errors[0]

    return exc_group


@asynccontextmanager
async def create_task_group() -> AsyncIterator[TaskGroup]:
    """Create an anyio task group that collapses single-error exception groups.

    Drop-in replacement for ``anyio.create_task_group()`` that automatically
    unwraps ``BaseExceptionGroup`` when there is exactly one non-cancellation
    error.  This makes error handling transparent for callers — they receive
    the original exception instead of a wrapped group.
    """
    try:
        async with anyio.create_task_group() as tg:
            yield tg
    except BaseExceptionGroup as eg:
        collapsed = collapse_exception_group(eg)
        if collapsed is not eg:
            raise collapsed from eg
        raise
