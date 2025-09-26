import inspect
import typing
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


def find_context_parameter(fn: Callable[..., Any]) -> str | None:
    """
    Inspect a function signature to find a parameter annotated with Context.
    Returns the name of the parameter if found, otherwise None.
    """
    from mcp.server.fastmcp import Context

    try:
        sig = inspect.signature(fn)
    except ValueError:  # pragma: no cover
        # Can't inspect signature (e.g. some builtins/wrappers)
        return None

    for param_name, param in sig.parameters.items():
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            continue

        # Handle Optional[Context], Annotated[Context, ...], etc.
        origin = typing.get_origin(annotation)

        # Check if the annotation itself is Context or a subclass
        if inspect.isclass(annotation) and issubclass(annotation, Context):
            return param_name

        # Check if it's a generic alias of Context (e.g., Context[...])
        if origin is not None and inspect.isclass(origin) and issubclass(origin, Context):
            return param_name  # pragma: no cover

    return None


def inject_context(
    fn: Callable[..., Any],
    kwargs: dict[str, Any],
    context: "Context[Any, Any, Any] | None",
    context_kwarg: str | None = None,
) -> dict[str, Any]:
    """
    Inject the Context object into kwargs if the function expects it.
    Returns the updated kwargs.
    """
    if context_kwarg is None:
        context_kwarg = find_context_parameter(fn)

    if context_kwarg:
        kwargs[context_kwarg] = context
    return kwargs
