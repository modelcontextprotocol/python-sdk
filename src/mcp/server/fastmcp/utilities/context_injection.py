"""Context injection utilities for FastMCP."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any


def find_context_parameter(fn: Callable[..., Any]) -> str | None:
    """Find the parameter that should receive the Context object.

    Searches through the function's signature to find a parameter
    with a Context type annotation.

    Args:
        fn: The function to inspect

    Returns:
        The name of the context parameter, or None if not found
    """
    from mcp.server.fastmcp.server import Context

    # Get type hints to properly resolve string annotations
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        # If we can't resolve type hints, we can't find the context parameter
        return None

    # Check each parameter's type hint
    for param_name, annotation in hints.items():
        # Handle direct Context type and generic aliases of Context
        origin = typing.get_origin(annotation)

        # Check if the annotation itself is Context or a subclass
        if inspect.isclass(annotation) and issubclass(annotation, Context):
            return param_name

        # Check if it's a generic alias of Context (e.g., Context[...])
        if origin is not None and inspect.isclass(origin) and issubclass(origin, Context):
            return param_name

    return None


def inject_context(
    fn: Callable[..., Any],
    kwargs: dict[str, Any],
    context: Any | None,
    context_kwarg: str | None,
) -> dict[str, Any]:
    """Inject context into function kwargs if needed.

    Args:
        fn: The function that will be called
        kwargs: The current keyword arguments
        context: The context object to inject (if any)
        context_kwarg: The name of the parameter to inject into

    Returns:
        Updated kwargs with context injected if applicable
    """
    if context_kwarg is not None and context is not None:
        return {**kwargs, context_kwarg: context}
    return kwargs
