import inspect
from collections.abc import Callable
from typing import Any


def accepts_cursor(func: Callable[..., Any]) -> bool:
    """
    True if the function accepts a cursor parameter call, otherwise false.

    `accepts_cursor` does not validate that the function will work. For
    example, if `func` contains keyword-only arguments with no defaults,
    then it will not work when used in the `lowlevel/server.py` code, but
    this function will not raise an exception.
    """
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return False

    params = dict(sig.parameters.items())

    if len(params) == 0:
        # No parameters at all - can't accept cursor
        return False

    # Check if ALL remaining parameters are keyword-only
    all_keyword_only = all(param.kind == inspect.Parameter.KEYWORD_ONLY for param in params.values())

    if all_keyword_only:
        # If all params are keyword-only, check if they ALL have defaults
        # If they do, the function can be called with no arguments -> no cursor
        all_have_defaults = all(param.default is not inspect.Parameter.empty for param in params.values())
        return not all_have_defaults  # False if all have defaults (no cursor), True otherwise

    # Check if the ONLY parameter is **kwargs (VAR_KEYWORD)
    # A function with only **kwargs can't accept a positional cursor argument
    if len(params) == 1:
        only_param = next(iter(params.values()))
        if only_param.kind == inspect.Parameter.VAR_KEYWORD:
            return False  # Can't pass positional cursor to **kwargs

    # Has at least one positional or variadic parameter - can accept cursor
    # Important note: this is designed to _not_ handle the situation where
    # there are multiple keyword only arguments with no defaults. In those
    # situations it's an invalid handler function, and will error. But it's
    # not the responsibility of this function to check the validity of a
    # callback.
    return True
