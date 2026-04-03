from __future__ import annotations

import functools
import inspect
from typing import Any


def is_async_callable(obj: Any) -> bool:
    while isinstance(obj, functools.partial):  # pragma: lax no cover
        obj = obj.func

    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )
