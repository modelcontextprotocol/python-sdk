"""Context injection utilities for FastMCP."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_origin


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

    sig = inspect.signature(fn)
    for param_name, param in sig.parameters.items():
        # Skip generic types
        if get_origin(param.annotation) is not None:
            continue

        # Check if parameter has annotation
        if param.annotation is not inspect.Parameter.empty:
            try:
                # Check if it's a Context subclass
                if issubclass(param.annotation, Context):
                    return param_name
            except TypeError:
                # issubclass raises TypeError for non-class types
                pass

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
