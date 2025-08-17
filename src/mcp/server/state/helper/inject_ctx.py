from __future__ import annotations

import inspect

from typing import Any, Callable, get_type_hints, get_origin, get_args, Union

from mcp.server.fastmcp.server import Context
from mcp.server.session import ServerSessionT
from mcp.shared.context import LifespanContextT, RequestT

from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


def _is_context_type(ann: Any) -> bool:
    """Return True if annotation is Context or wraps Context (Union/Annotated)."""
    if isinstance(ann, type):
        return issubclass(ann, Context)

    origin = get_origin(ann)
    if origin is Union or str(origin) in {"typing.Union", "types.UnionType"}:
        return any(_is_context_type(a) for a in get_args(ann))

    if str(origin) == "typing.Annotated":
        args = get_args(ann)
        return bool(args) and _is_context_type(args[0])

    return False


def inject_context(
    fn: Callable[..., Any],
    ctx: Context[ServerSessionT, LifespanContextT, RequestT] | None,
    arguments: dict[str, Any] | None = None,
) -> Any:
    """
    Call `fn` with given arguments, injecting `ctx` into any parameters annotated
    as Context (or Optional/Annotated Context). If `ctx` is None, inject None and log a warning.
    """

    # Resolve annotations (with extras, so Annotated works)
    try:
        resolved = get_type_hints(fn, globalns=fn.__globals__, include_extras=True)
    except Exception:
        # fallback if resolution fails
        resolved = {name: p.annotation for name, p in inspect.signature(fn).parameters.items()}

    sig = inspect.signature(fn)
    call_args = dict(arguments or {})

    for name, param in sig.parameters.items():
        if name in call_args:
            continue  # user already provided, don't overwrite
        ann: Any = resolved.get(name, param.annotation)
        if _is_context_type(ann):
            if ctx is None:
                logger.warning(
                    "Function %s expects Context parameter '%s', but ctx=None; injecting None",
                    fn.__name__,
                    name,
                )
            logger.debug("Injecting context parameter for target '%s'.", name)
            call_args[name] = ctx

    return fn(**call_args)

    
