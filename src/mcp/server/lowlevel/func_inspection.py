import inspect
from collections.abc import Callable
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")
R = TypeVar("R")


def _type_matches_request(param_type: Any, request_type: type[T]) -> bool:
    """
    Check if a parameter type matches the request type.

    This handles direct matches, Union types (e.g., RequestType | None),
    and Optional types (e.g., Optional[RequestType]).
    """
    if param_type == request_type:
        return True

    origin = get_origin(param_type)
    args = get_args(param_type)

    # Handle typing.Union and Python 3.10+ | syntax
    if origin is Union:
        return request_type in args

    # Handle types.UnionType from Python 3.10+ | syntax
    if hasattr(param_type, "__args__") and args:
        return request_type in args

    return False


def create_call_wrapper(func: Callable[..., R], request_type: type[T]) -> Callable[[T], R]:
    """
    Create a wrapper function that knows how to call func with the request object.

    Returns a wrapper function that takes the request and calls func appropriately.

    The wrapper handles three calling patterns:
    1. Positional-only parameter typed as request_type or Union containing request_type: func(req)
    2. Positional/keyword parameter typed as request_type or Union containing request_type: func(**{param_name: req})
    3. No matching request parameter: func()

    Union types like `RequestType | None` and `Optional[RequestType]` are supported,
    allowing for optional request parameters with default values.
    """
    try:
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)
    except (ValueError, TypeError, NameError):
        return lambda _: func()

    # Check for positional-only parameter typed as request_type
    for param_name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            param_type = type_hints.get(param_name)
            if _type_matches_request(param_type, request_type):
                # Found positional-only parameter with correct type
                return lambda req: func(req)

    # Check for any positional/keyword parameter typed as request_type
    for param_name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            param_type = type_hints.get(param_name)
            if _type_matches_request(param_type, request_type):
                # Found keyword parameter with correct type
                # Need to capture param_name in closure properly
                def make_keyword_wrapper(name: str) -> Callable[[Any], Any]:
                    return lambda req: func(**{name: req})

                return make_keyword_wrapper(param_name)

    # No request parameter found - use old style
    return lambda _: func()
