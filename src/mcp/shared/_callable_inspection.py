"""Callable inspection utilities.

Adapted from Starlette's `is_async_callable` implementation.
https://github.com/encode/starlette/blob/main/starlette/_utils.py
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


def split_positional_args(
    fn: Callable[..., Any], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Split kwargs into positional-only arguments and remaining keyword arguments.

    If `fn` accepts positional-only parameters, extracts matching arguments from
    `kwargs` in positional order.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return (), kwargs

    pos_only_params = [
        p for p in sig.parameters.values()
        if p.kind == inspect.Parameter.POSITIONAL_ONLY
    ]
    if not pos_only_params:
        return (), kwargs

    pos_args: list[Any] = []
    remaining_kwargs = dict(kwargs)
    for p in pos_only_params:
        if p.name in remaining_kwargs:
            pos_args.append(remaining_kwargs.pop(p.name))
        elif p.default is not inspect.Parameter.empty:
            idx = pos_only_params.index(p)
            has_later = any(later.name in remaining_kwargs for later in pos_only_params[idx + 1 :])
            if has_later:
                pos_args.append(p.default)
            else:
                break
        else:
            break

    return tuple(pos_args), remaining_kwargs
