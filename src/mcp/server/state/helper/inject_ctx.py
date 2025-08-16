from __future__ import annotations

import inspect

from typing import Any, Callable, Optional, get_type_hints, get_origin, get_args, Union

from mcp.server.fastmcp.server import Context
from mcp.server.state.types import FastMCPContext

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


def inject_context(fn: Callable[..., Any], ctx: FastMCPContext | None) -> Any:
    """
    If `fn` has a parameter annotated as Context (or Optional/Annotated Context),
    inject `ctx` by keyword. If `ctx` is None, log a warning and inject None anyway.
    If no Context parameter exists, call without injection.

    Works with future annotations via get_type_hints().
    """

    # extract params
    try:
        resolved = get_type_hints(fn, globalns=fn.__globals__, localns=None, include_extras=True)
    except Exception:
        # Fallback if resolution fails (string annotations may limit detection)
        resolved = {name: p.annotation for name, p in inspect.signature(fn).parameters.items()}

    # check params for context
    target: Optional[str] = None
    sig = inspect.signature(fn)
    for name, param in sig.parameters.items():
        ann: Any = resolved.get(name, param.annotation)
        if _is_context_type(ann):
            target = name
            break

    if target is None:
        logger.debug("No context parameter found to inject.")
        return fn()

    if ctx is None:
        logger.warning(
            "Transition callback expects a Context parameter '%s', but provided context is None; injecting None.",
            target,
        )

    logger.debug("Injected context parameter for target '%s'.", target)

    return fn(**{target: ctx})
