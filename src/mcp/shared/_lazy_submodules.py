"""Lazy submodule access for packages (PEP 562 module `__getattr__` factory).

A bare `import mcp` used to import most of the SDK eagerly, so attribute chains
such as `mcp.client.stdio.stdio_client` resolved without ever importing the
submodule explicitly. The `mcp` package is lazy now; a package that installs
this `__getattr__` keeps such chains working - touching `pkg.<name>` imports the
submodule `pkg.<name>` when there is one - without importing anything up front.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module


def submodule_getattr(package_name: str) -> Callable[[str], object]:
    """Build a module `__getattr__` that imports `package_name.<attr>` on demand."""

    def __getattr__(name: str) -> object:
        if name.startswith("__"):
            # Dunder lookups (`__test__`, `__path__`, ...) are protocol probes,
            # never submodules; answer them without a filesystem search.
            raise AttributeError(f"module {package_name!r} has no attribute {name!r}")
        module_name = f"{package_name}.{name}"
        try:
            return import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                # A submodule that exists but has a missing dependency of its
                # own: surface the real ImportError, not a misleading AttributeError.
                raise
            raise AttributeError(f"module {package_name!r} has no attribute {name!r}") from None

    return __getattr__
