from collections.abc import Callable
from typing import Any

import pytest

from mcp import types
from mcp.server.lowlevel.func_inspection import accepts_request


# Test fixtures - functions and methods with various signatures
class MyClass:
    async def no_request_method(self):
        """Instance method without request parameter"""
        pass

    # noinspection PyMethodParameters
    async def no_request_method_bad_self_name(bad):  # pyright: ignore[reportSelfClsParameterName]
        """Instance method without request parameter, but with bad self name"""
        pass

    async def request_method(self, request: types.ListPromptsRequest):
        """Instance method with request parameter"""
        pass

    # noinspection PyMethodParameters
    async def request_method_bad_self_name(bad, request: types.ListPromptsRequest):  # pyright: ignore[reportSelfClsParameterName]
        """Instance method with request parameter, but with bad self name"""
        pass

    @classmethod
    async def no_request_class_method(cls):
        """Class method without request parameter"""
        pass

    # noinspection PyMethodParameters
    @classmethod
    async def no_request_class_method_bad_cls_name(bad):  # pyright: ignore[reportSelfClsParameterName]
        """Class method without request parameter, but with bad cls name"""
        pass

    @classmethod
    async def request_class_method(cls, request: types.ListPromptsRequest):
        """Class method with request parameter"""
        pass

    # noinspection PyMethodParameters
    @classmethod
    async def request_class_method_bad_cls_name(bad, request: types.ListPromptsRequest):  # pyright: ignore[reportSelfClsParameterName]
        """Class method with request parameter, but with bad cls name"""
        pass

    @staticmethod
    async def no_request_static_method():
        """Static method without request parameter"""
        pass

    @staticmethod
    async def request_static_method(request: types.ListPromptsRequest):
        """Static method with request parameter"""
        pass

    @staticmethod
    async def request_static_method_bad_arg_name(self: types.ListPromptsRequest):  # pyright: ignore[reportSelfClsParameterName]
        """Static method with request parameter, but the request argument is named self"""
        pass


async def no_request_func():
    """Function without request parameter"""
    pass


async def request_func(request: types.ListPromptsRequest):
    """Function with request parameter"""
    pass


async def request_func_different_name(req: types.ListPromptsRequest):
    """Function with request parameter but different arg name"""
    pass


async def request_func_with_self(self: types.ListPromptsRequest):
    """Function with parameter named 'self' (edge case)"""
    pass


async def var_positional_func(*args: Any):
    """Function with *args"""
    pass


async def positional_with_var_positional_func(request: types.ListPromptsRequest, *args: Any):
    """Function with request and *args"""
    pass


async def var_keyword_func(**kwargs: Any):
    """Function with **kwargs"""
    pass


async def request_with_var_keyword_func(request: types.ListPromptsRequest, **kwargs: Any):
    """Function with request and **kwargs"""
    pass


async def request_with_default(request: types.ListPromptsRequest | None = None):
    """Function with request parameter having default value"""
    pass


async def keyword_only_with_defaults(*, request: types.ListPromptsRequest | None = None):
    """Function with keyword-only request with default"""
    pass


async def keyword_only_multiple_all_defaults(*, a: str = "test", b: int = 42):
    """Function with multiple keyword-only params all with defaults"""
    pass


async def mixed_positional_and_keyword(request: types.ListPromptsRequest, *, extra: str = "test"):
    """Function with positional and keyword-only params"""
    pass


@pytest.mark.parametrize(
    "callable_obj,expected,description",
    [
        # Regular functions
        (no_request_func, False, "function without parameters"),
        (request_func, True, "function with request parameter"),
        (request_func_different_name, True, "function with request (different param name)"),
        (request_func_with_self, True, "function with param named 'self'"),
        # Instance methods
        (MyClass().no_request_method, False, "instance method without request"),
        (MyClass().no_request_method_bad_self_name, False, "instance method without request (bad self name)"),
        (MyClass().request_method, True, "instance method with request"),
        (MyClass().request_method_bad_self_name, True, "instance method with request (bad self name)"),
        # Class methods
        (MyClass.no_request_class_method, False, "class method without request"),
        (MyClass.no_request_class_method_bad_cls_name, False, "class method without request (bad cls name)"),
        (MyClass.request_class_method, True, "class method with request"),
        (MyClass.request_class_method_bad_cls_name, True, "class method with request (bad cls name)"),
        # Static methods
        (MyClass.no_request_static_method, False, "static method without request"),
        (MyClass.request_static_method, True, "static method with request"),
        (MyClass.request_static_method_bad_arg_name, True, "static method with request (bad arg name)"),
        # Variadic parameters
        (var_positional_func, True, "function with *args"),
        (positional_with_var_positional_func, True, "function with request and *args"),
        (var_keyword_func, False, "function with **kwargs"),
        (request_with_var_keyword_func, True, "function with request and **kwargs"),
        # Edge cases
        (request_with_default, True, "function with request having default value"),
        # Keyword-only parameters
        (keyword_only_with_defaults, False, "keyword-only with default (can call with no args)"),
        (keyword_only_multiple_all_defaults, False, "multiple keyword-only all with defaults"),
        (mixed_positional_and_keyword, True, "mixed positional and keyword-only params"),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_accepts_request(callable_obj: Callable[..., Any], expected: bool, description: str):
    """Test that accepts_request correctly identifies functions that accept a request parameter.

    The function should return True if the callable can potentially accept a positional
    request argument. Returns False if:
    - No parameters at all
    - Only keyword-only parameters that ALL have defaults (can call with no args)
    - Only **kwargs parameter (can't accept positional arguments)
    """
    assert accepts_request(callable_obj) == expected, f"Failed for {description}"
