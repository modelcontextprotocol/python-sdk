"""Context injection utilities for MCPServer."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.context import Context


def find_context_parameter(fn: Callable[..., Any]) -> str | None:
    """Find the name of the parameter annotated with a Context type, or None."""
    # get_type_hints (rather than raw annotations) so string annotations resolve
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # pragma: lax no cover
        return None

    for param_name, annotation in hints.items():
        if inspect.isclass(annotation) and issubclass(annotation, Context):
            return param_name

        # generic annotations like Optional[Context]
        origin = typing.get_origin(annotation)
        if origin is not None:
            args = typing.get_args(annotation)
            for arg in args:
                if inspect.isclass(arg) and issubclass(arg, Context):
                    return param_name

    return None


def inject_context(
    fn: Callable[..., Any],
    kwargs: dict[str, Any],
    context: Any | None,
    context_kwarg: str | None,
) -> dict[str, Any]:
    """Return kwargs with `context` added under `context_kwarg` when both are set."""
    if context_kwarg is not None and context is not None:
        return {**kwargs, context_kwarg: context}
    return kwargs
