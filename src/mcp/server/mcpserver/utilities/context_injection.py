"""Context injection utilities for MCPServer."""

from __future__ import annotations

import functools
import inspect
import typing
from collections.abc import Callable
from typing import Any

from pydantic import SkipValidation, validate_call

from mcp.server.mcpserver.context import Context
from mcp.shared._callable_inspection import is_async_callable


def find_context_parameter(fn: Callable[..., Any]) -> str | None:
    """Find the parameter that should receive the Context object.

    Searches through the function's signature to find a parameter
    with a Context type annotation.

    Args:
        fn: The function to inspect

    Returns:
        The name of the context parameter, or None if not found
    """
    # Get type hints to properly resolve string annotations
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # pragma: lax no cover
        # If we can't resolve type hints, we can't find the context parameter
        return None

    # Check each parameter's type hint
    for param_name, annotation in hints.items():
        # Handle direct Context type
        if inspect.isclass(annotation) and issubclass(annotation, Context):
            return param_name

        # Handle generic types like Optional[Context]
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


def validate_call_with_injected_context(
    fn: Callable[..., Any],
    context_kwarg: str | None,
) -> Callable[..., Any]:
    """Validate a handler call without re-validating its injected context."""
    if context_kwarg is None:
        return validate_call(fn)

    signature = inspect.signature(fn, eval_str=True)
    context_parameter = signature.parameters.get(context_kwarg)
    if context_parameter is None:
        return validate_call(fn)

    context_annotation = typing.get_type_hints(fn, include_extras=True).get(context_kwarg, Any)
    skipped_context_annotation = SkipValidation[context_annotation]
    validation_signature = signature.replace(
        parameters=[
            parameter.replace(annotation=skipped_context_annotation) if parameter.name == context_kwarg else parameter
            for parameter in signature.parameters.values()
        ]
    )
    validation_annotations = {
        parameter.name: parameter.annotation
        for parameter in validation_signature.parameters.values()
        if parameter.annotation is not inspect.Parameter.empty
    }
    if is_async_callable(fn):

        @functools.wraps(fn)
        async def async_forwarding(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        forwarding: Callable[..., Any] = async_forwarding
    else:

        @functools.wraps(fn)
        def sync_forwarding(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        forwarding = sync_forwarding

    # Pydantic builds its validator from these temporary annotations. Restore the
    # handler's public signature after validation is compiled.
    setattr(forwarding, "__signature__", validation_signature)
    forwarding.__annotations__ = validation_annotations
    validated = validate_call(forwarding)
    setattr(validated, "__signature__", signature)
    validated.__annotations__ = fn.__annotations__
    return validated
