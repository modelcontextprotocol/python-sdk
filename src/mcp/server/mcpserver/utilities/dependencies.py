"""Dependency injection system for MCPServer."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Depends(Generic[T]):
    """Marker class for dependency injection.

    Usage:
        def get_db() -> Database:
            return Database()

        @server.tool()
        def my_tool(db: Database = Depends(get_db)):
            return db.query(...)

    Args:
        dependency: A callable that provides the dependency
        scope: The scope of the dependency (for future use)
        use_cache: Whether to cache the dependency result

    """

    def __init__(
        self,
        dependency: Callable[..., T],
        *,
        use_cache: bool = True,
    ) -> None:
        self.dependency = dependency
        self.use_cache = use_cache

    def __repr__(self) -> str:
        return f"Depends({self.dependency.__name__})"


def find_dependency_parameters(
    fn: Callable[..., Any],
) -> dict[str, Depends[Any]]:
    """Find all parameters with Depends() default values.

    Args:
        fn: Function to inspect

    Returns:
        Dict mapping parameter names to Depends instances
    """
    deps: dict[str, Depends[Any]] = {}
    try:
        sig = inspect.signature(fn, eval_str=True)
    except (ValueError, TypeError):  # pragma: no cover (defensive)
        return deps

    for param_name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            continue

        # Check if default is Depends instance
        if isinstance(param.default, Depends):
            deps[param_name] = param.default  # type: ignore[assignment]

    return deps
