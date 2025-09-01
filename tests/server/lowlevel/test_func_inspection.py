from collections.abc import Callable
from typing import Any

import pytest

from mcp import types
from mcp.server.lowlevel.func_inspection import accepts_cursor


# Test fixtures - functions and methods with various signatures
class MyClass:
    async def no_cursor_method(self):
        """Instance method without cursor parameter"""
        pass

    # noinspection PyMethodParameters
    async def no_cursor_method_bad_self_name(bad):  # pyright: ignore[reportSelfClsParameterName]
        """Instance method with cursor parameter, but with bad self name"""
        pass

    async def cursor_method(self, cursor: types.Cursor | None):
        """Instance method with cursor parameter"""
        pass

    # noinspection PyMethodParameters
    async def cursor_method_bad_self_name(bad, cursor: types.Cursor | None):  # pyright: ignore[reportSelfClsParameterName]
        """Instance method with cursor parameter, but with bad self name"""
        pass

    @classmethod
    async def no_cursor_class_method(cls):
        """Class method without cursor parameter"""
        pass

    # noinspection PyMethodParameters
    @classmethod
    async def no_cursor_class_method_bad_cls_name(bad):  # pyright: ignore[reportSelfClsParameterName]
        """Class method without cursor parameter, but with bad cls name"""
        pass

    @classmethod
    async def cursor_class_method(cls, cursor: types.Cursor | None):
        """Class method with cursor parameter"""
        pass

    # noinspection PyMethodParameters
    @classmethod
    async def cursor_class_method_bad_cls_name(bad, cursor: types.Cursor | None):  # pyright: ignore[reportSelfClsParameterName]
        """Class method with cursor parameter, but with bad cls name"""
        pass

    @staticmethod
    async def no_cursor_static_method():
        """Static method without cursor parameter"""
        pass

    @staticmethod
    async def cursor_static_method(cursor: types.Cursor | None):
        """Static method with cursor parameter"""
        pass

    @staticmethod
    async def cursor_static_method_bad_arg_name(self: types.Cursor | None):  # pyright: ignore[reportSelfClsParameterName]
        """Static method with cursor parameter, but the cursor argument is named self"""
        pass


async def no_cursor_func():
    """Function without cursor parameter"""
    pass


async def cursor_func(cursor: types.Cursor | None):
    """Function with cursor parameter"""
    pass


async def cursor_func_different_name(c: types.Cursor | None):
    """Function with cursor parameter but different arg name"""
    pass


async def cursor_func_with_self(self: types.Cursor | None):
    """Function with parameter named 'self' (edge case)"""
    pass


async def var_positional_func(*args: Any):
    """Function with *args"""
    pass


async def positional_with_var_positional_func(cursor: types.Cursor | None, *args: Any):
    """Function with cursor and *args"""
    pass


async def var_keyword_func(**kwargs: Any):
    """Function with **kwargs"""
    pass


async def cursor_with_var_keyword_func(cursor: types.Cursor | None, **kwargs: Any):
    """Function with cursor and **kwargs"""
    pass


async def cursor_with_default(cursor: types.Cursor | None = None):
    """Function with cursor parameter having default value"""
    pass


async def keyword_only_with_defaults(*, cursor: types.Cursor | None = None):
    """Function with keyword-only cursor with default"""
    pass


async def keyword_only_multiple_all_defaults(*, a: str = "test", b: int = 42):
    """Function with multiple keyword-only params all with defaults"""
    pass


async def mixed_positional_and_keyword(cursor: types.Cursor | None, *, extra: str = "test"):
    """Function with positional and keyword-only params"""
    pass


@pytest.mark.parametrize(
    "callable_obj,expected,description",
    [
        # Regular functions
        (no_cursor_func, False, "function without parameters"),
        (cursor_func, True, "function with cursor parameter"),
        (cursor_func_different_name, True, "function with cursor (different param name)"),
        (cursor_func_with_self, True, "function with param named 'self'"),
        # Instance methods
        (MyClass().no_cursor_method, False, "instance method without cursor"),
        (MyClass().no_cursor_method_bad_self_name, False, "instance method without cursor (bad self name)"),
        (MyClass().cursor_method, True, "instance method with cursor"),
        (MyClass().cursor_method_bad_self_name, True, "instance method with cursor (bad self name)"),
        # Class methods
        (MyClass.no_cursor_class_method, False, "class method without cursor"),
        (MyClass.no_cursor_class_method_bad_cls_name, False, "class method without cursor (bad cls name)"),
        (MyClass.cursor_class_method, True, "class method with cursor"),
        (MyClass.cursor_class_method_bad_cls_name, True, "class method with cursor (bad cls name)"),
        # Static methods
        (MyClass.no_cursor_static_method, False, "static method without cursor"),
        (MyClass.cursor_static_method, True, "static method with cursor"),
        (MyClass.cursor_static_method_bad_arg_name, True, "static method with cursor (bad arg name)"),
        # Variadic parameters
        (var_positional_func, True, "function with *args"),
        (positional_with_var_positional_func, True, "function with cursor and *args"),
        (var_keyword_func, False, "function with **kwargs"),
        (cursor_with_var_keyword_func, True, "function with cursor and **kwargs"),
        # Edge cases
        (cursor_with_default, True, "function with cursor having default value"),
        # Keyword-only parameters
        (keyword_only_with_defaults, False, "keyword-only with default (can call with no args)"),
        (keyword_only_multiple_all_defaults, False, "multiple keyword-only all with defaults"),
        (mixed_positional_and_keyword, True, "mixed positional and keyword-only params"),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_accepts_cursor(callable_obj: Callable[..., Any], expected: bool, description: str):
    """Test that accepts_cursor correctly identifies functions that accept a cursor parameter.

    The function should return True if the callable can potentially accept a positional
    cursor argument. Returns False if:
    - No parameters at all
    - Only keyword-only parameters that ALL have defaults (can call with no args)
    - Only **kwargs parameter (can't accept positional arguments)
    """
    assert accepts_cursor(callable_obj) == expected, f"Failed for {description}"
