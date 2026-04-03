"""Callable inspection utilities.

Adapted from Starlette's `is_async_callable` implementation.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeGuard, TypeVar, overload

T = TypeVar("T")

AwaitableCallable = Callable[..., Awaitable[T]]


@overload
def is_async_callable(obj: AwaitableCallable[T]) -> TypeGuard[AwaitableCallable[T]]: ...


@overload
def is_async_callable(obj: Any) -> TypeGuard[AwaitableCallable[Any]]: ...


def is_async_callable(obj: Any) -> Any:
    while isinstance(obj, functools.partial):  # pragma: lax no cover
        obj = obj.func

    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )
