"""Callable inspection utilities.

Adapted from Starlette's `is_async_callable` implementation.
https://github.com/encode/starlette/blob/main/starlette/_utils.py
"""

from __future__ import annotations

import functools
import inspect
import sys
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeGuard, TypeVar, overload

if sys.version_info >= (3, 14):  # pragma: no cover - version-dependent import
    import annotationlib

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


def signature_parameters(fn: Callable[..., Any]) -> Mapping[str, inspect.Parameter]:
    """Parameters of `fn` by name, without evaluating its annotations.

    Callers that only need the names must not force evaluation: on Python 3.14+
    (PEP 649) annotations are evaluated lazily through `__annotate__`, and
    `inspect.signature` evaluates them by default, so a parameter whose type the
    module has not finished defining raises a bare `NameError` from a call that
    never wanted the type. `Format.FORWARDREF` leaves them unevaluated; on older
    Pythons string annotations are already returned unevaluated, so the plain
    call is safe there.
    """
    if sys.version_info >= (3, 14):
        return inspect.signature(fn, annotation_format=annotationlib.Format.FORWARDREF).parameters
    return inspect.signature(fn).parameters
