import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from mcp.types import Depends


def find_dependencies(fn: Callable[..., Any]) -> dict[str, Depends]:
    """Find all dependencies in a function's parameters."""
    # Get type hints to properly resolve string annotations
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        # If we can't resolve type hints, we can't find dependencies
        hints = {}

    dependencies: dict[str, Depends] = {}

    # Get function signature to access parameter defaults
    sig = inspect.signature(fn)

    # Check each parameter's type hint and default value
    for param_name, param in sig.parameters.items():
        # Check if it's in Annotated form
        if param_name in hints:
            annotation = hints[param_name]
            if get_origin(annotation) is Annotated:
                _, *extras = get_args(annotation)
                dep = next((x for x in extras if isinstance(x, Depends)), None)
                if dep is not None:
                    dependencies[param_name] = dep
                    continue

        # Check if default value is a Depends instance
        if param.default is not inspect.Parameter.empty and isinstance(param.default, Depends):
            dependencies[param_name] = param.default

    return dependencies


def _is_async_callable(obj: Any) -> bool:
    """Check if a callable is async."""
    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )


def _is_generator_function(obj: Any) -> bool:
    """Check if a callable is a generator function."""
    return inspect.isgeneratorfunction(obj)


def _is_async_generator_function(obj: Any) -> bool:
    """Check if a callable is an async generator function."""
    return inspect.isasyncgenfunction(obj)


class DependencyResolver:
    """Resolve dependencies and clean up properly when errors occur."""

    def __init__(self):
        self._generators: list[Generator[Any, None, None]] = []
        self._async_generators: list[AsyncGenerator[Any, None]] = []

    async def resolve_dependencies(self, dependencies: dict[str, Depends]) -> dict[str, Any]:
        """Resolve all dependencies and return their values."""
        if not dependencies:
            return {}

        resolved: dict[str, Any] = {}

        for param_name, depends in dependencies.items():
            try:
                resolved[param_name] = await self._resolve_single_dependency(depends)
            except Exception as e:
                # Cleanup any generators and async generators that were already created
                await self.cleanup()
                raise RuntimeError(f"Failed to resolve dependency '{param_name}': {e}") from e

        return resolved

    async def _resolve_single_dependency(self, depends: Depends) -> Any:
        """Resolve a single dependency."""
        dependency_fn = depends.dependency

        if _is_async_generator_function(dependency_fn):
            gen = dependency_fn()
            self._async_generators.append(gen)
            try:
                value = await gen.__anext__()
                return value
            except StopAsyncIteration:
                raise RuntimeError(f"Async generator dependency {dependency_fn.__name__} didn't yield a value")

        elif _is_generator_function(dependency_fn):
            gen = dependency_fn()
            self._generators.append(gen)
            try:
                value = next(gen)
                return value
            except StopIteration:
                raise RuntimeError(f"Generator dependency {dependency_fn.__name__} didn't yield a value")

        elif _is_async_callable(dependency_fn):
            return await dependency_fn()

        else:
            return dependency_fn()

    async def cleanup(self):
        """Cleanup all generator dependencies."""
        for gen in self._async_generators:
            try:
                await gen.aclose()
            except Exception:
                pass

        for gen in self._generators:
            try:
                gen.close()
            except Exception:
                pass

        self._generators.clear()
        self._async_generators.clear()
