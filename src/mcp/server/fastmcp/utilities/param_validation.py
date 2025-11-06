"""Utility functions for validating and aligning function parameters with URI templates."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Annotated, Any, get_args, get_origin

from pydantic.version import VERSION as PYDANTIC_VERSION

from mcp.server.fastmcp.utilities.convertors import CONVERTOR_TYPES, Convertor
from mcp.server.fastmcp.utilities.params import Path, Query

PYDANTIC_VERSION_MINOR_TUPLE = tuple(int(x) for x in PYDANTIC_VERSION.split(".")[:2])
PYDANTIC_V2 = PYDANTIC_VERSION_MINOR_TUPLE[0] == 2

if not PYDANTIC_V2:
    from pydantic.fields import Undefined  # type: ignore[attr-defined]
else:
    from pydantic.v1.fields import Undefined

# difference between not given not needed, not given maybe needed.
_Unset: Any = Undefined  # type: ignore


def validate_and_sync_params(
    fn: Callable[..., Any],
    uri_template: str,
) -> tuple[
    set[str],  # path_params
    set[str],  # required_query_params
    set[str],  # optional_query_params
    dict[str, Convertor[Any]],
    re.Pattern[str],
]:
    """
    Analyze a function signature and URI template to:
    - Collect parameter types from the function
    - Validate and align URI parameters with the function signature
    - Infer or validate types between both sides
    - Build regex pattern and converters

    Returns:
        (path_params, required_query_params, optional_query_params, converters, compiled_pattern, fn_defaults)
    """
    fn_param_types, explicit_path_params, fn_defaults, ignore_query_params = _extract_function_params(fn)
    parts = uri_template.strip("/").split("/")

    uri_pattern, converters, path_params = _parse_uri_and_validate_types(fn.__name__, parts, fn_param_types)

    path_params, required_query, optional_query = _postprocess_params(
        ignore_query_params, fn_param_types, explicit_path_params, fn_defaults, path_params, parts
    )

    return path_params, required_query, optional_query, converters, uri_pattern


def _extract_function_params(
    fn: Callable[..., Any],
) -> tuple[dict[str, Any], set[str], dict[str, Any], set[str]]:
    """
    Extract parameter types and defaults from the function signature.
    Detect explicitly annotated Path parameters (Annotated[..., Path()]).
    """
    IGNORE_TYPES: set[str] = {"Context"}
    sig = inspect.signature(fn)
    fn_param_types: dict[str, Any] = {}
    explicit_path: set[str] = set()
    fn_defaults: dict[str, Any] = {}
    ignore_query_params: set[str] = set()
    for name, param in sig.parameters.items():
        base_type = param.annotation
        if get_origin(param.annotation) is Annotated:
            args = get_args(param.annotation)
            if args:
                base_type = args[0]
                for meta in args[1:]:
                    if isinstance(meta, Path):
                        explicit_path.add(name)
                    if isinstance(meta, Query):
                        if meta.default is not Undefined:
                            fn_defaults[name] = meta.default

        fn_param_types[name] = base_type

        # IGNORE TYPES caused a circular import with Context so using it as a string
        # defaults are optional query, path cannot have defaults
        # In a weird way have to do this to get base(origin) for Context
        def get_base(name: str) -> str:
            return name.split("[")[0]

        base = get_base(param.annotation.__name__)
        if base in IGNORE_TYPES:
            ignore_query_params.add(name)
        if param.default is not inspect._empty:  # type: ignore
            fn_defaults[name] = param.default
    return fn_param_types, explicit_path, fn_defaults, ignore_query_params


def _parse_uri_and_validate_types(
    fn_name: str, parts: list[str], fn_param_types: dict[str, Any]
) -> tuple[re.Pattern[str], dict[str, Convertor[Any]], set[str]]:
    """
    Parse URI path components, infer or validate types, and build converters.
    Returns a compiled regex pattern, converter mapping, and detected path parameters.
    """
    pattern_parts: list[str] = []
    converters: dict[str, Convertor[Any]] = {}
    path_params: set[str] = set()

    for part in parts:
        match = re.fullmatch(r"\{(\w+)(?::(\w+))?\}", part)
        if not match:
            pattern_parts.append(re.escape(part))
            continue

        name, uri_type = match.groups()
        if name not in fn_param_types:
            raise ValueError(
                f"Mismatch between URI path parameters '{name}' and required function parameters in '{fn_name}'"
            )

        fn_type = fn_param_types[name]
        uri_type = _resolve_type(name, uri_type, fn_type)

        if uri_type not in CONVERTOR_TYPES:
            raise NotImplementedError(f"Parameter '{name}' in URI uses unsupported type '{uri_type}'.")

        conv = CONVERTOR_TYPES[uri_type]
        converters[name] = conv
        pattern_parts.append(f"(?P<{name}>{conv.regex})")
        path_params.add(name)

    uri_pattern = re.compile("^" + "/".join(pattern_parts) + "$")
    return uri_pattern, converters, path_params


def _resolve_type(name: str, uri_type: str | None, fn_type: Any) -> str:
    """
    Infer or validate type consistency between URI and function parameter.
    - If only one side defines a type, the other inherits it.
    - If both define types, they must be compatible.
    """
    if uri_type and uri_type not in CONVERTOR_TYPES:
        raise NotImplementedError(f"Unknown converter type '{uri_type}' in URI template")

    if uri_type is None:
        if fn_type is not inspect._empty:  # type: ignore
            tname = getattr(fn_type, "__name__", None)
            if tname in CONVERTOR_TYPES:
                return tname
        return "str"

    if fn_type is not inspect._empty and uri_type in CONVERTOR_TYPES:  # type: ignore
        expected_type = CONVERTOR_TYPES[uri_type].python_type
        if fn_type != expected_type and not issubclass(fn_type, expected_type):
            raise TypeError(
                f"Type mismatch for '{name}': URI declares {expected_type.__name__}, "
                f"function declares {getattr(fn_type, '__name__', fn_type)}"
            )

    return uri_type


def _postprocess_params(
    ignore_query_params: set[str],
    fn_param_types: dict[str, Any],
    explicit_path: set[str],
    fn_defaults: dict[str, Any],
    path_params: set[str],
    parts: list[str],
) -> tuple[set[str], set[str], set[str]]:
    """
    Perform final validation and classification of parameters:
    - Ensure 'path' converters only appear as the last URI segment
    - Ensure explicitly declared Path parameters exist in the URI
    - Derive query parameters as required or optional based on defaults
    """
    # Validate 'path' types appear last
    for i, part in enumerate(parts):
        match = re.fullmatch(r"\{(\w+)(?::(\w+))?\}", part)
        if not match:
            continue
        _, uri_type = match.groups()
        if uri_type == "path" and i != len(parts) - 1:
            raise ValueError("Path parameters must appear last in the URI template")

    # Ensure explicit Path() parameters exist in URI
    missing = explicit_path - path_params
    if missing:
        raise ValueError(f"Explicit Path parameters {missing} are not present in URI template")

    # Ensure path parameters dont have defaults.
    if not path_params.isdisjoint(fn_defaults.keys()):
        raise ValueError("Path parameters cannot have defaults.")

    # Everything not in path_params and ingore_query_params is a query param
    def is_query_param(name: str) -> bool:
        return name not in path_params and name not in ignore_query_params

    query_params = {name for name in fn_param_types if is_query_param(name)}

    required_query = {n for n in query_params if n not in fn_defaults}
    optional_query = {n for n in query_params if n in fn_defaults}

    return path_params, required_query, optional_query
