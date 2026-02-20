"""Dependency resolution engine."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.utilities.dependencies import Depends


class DependencyResolver:
    """Resolves dependency graphs and provides dependency instances."""

    def __init__(self, context: Any = None, overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None):
        """Initialize the resolver.

        Args:
            context: Optional context object to pass to dependencies
            overrides: Dictionary mapping original dependencies to their overrides
        """
        self._context = context
        self._overrides = overrides or {}
        self._cache: dict[Callable[..., Any], Any] = {}

    async def resolve(
        self,
        param_name: str,
        depends: Depends[Any],
    ) -> Any:
        """Resolve a single dependency and its dependencies.

        Args:
            param_name: The name of the parameter receiving the dependency
            depends: The Depends instance to resolve

        Returns:
            The resolved dependency value
        """
        # Check if there's an override
        dependency_fn = self._overrides.get(depends.dependency, depends.dependency)

        # Check cache first
        if depends.use_cache and dependency_fn in self._cache:
            return self._cache[dependency_fn]

        # Resolve nested dependencies recursively
        from mcp.server.mcpserver.utilities.dependencies import find_dependency_parameters

        sub_deps = find_dependency_parameters(dependency_fn)
        resolved_sub_deps = {}
        for sub_name, sub_depends in sub_deps.items():
            resolved_sub_deps[sub_name] = await self.resolve(sub_name, sub_depends)

        # Call the dependency function
        result = dependency_fn(**resolved_sub_deps)
        if inspect.iscoroutine(result):
            result = await result

        # Cache if appropriate
        if depends.use_cache:
            self._cache[dependency_fn] = result

        return result
