from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from typing_extensions import ParamSpec

P = ParamSpec("P")
R = TypeVar("R")


def instrument(func: Callable[P, R]) -> Callable[P, R]:
    """
    Example decorator that logs before/after the call
    while preserving the original function's type signature.
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return func(*args, **kwargs)

    return wrapper
