"""Lazy module attributes (PEP 562) shared by the SDK's package inits.

`import mcp` no longer walks the SDK's whole module graph; each package instead
resolves what it exports the first time it is asked for it. `lazy_module_attrs`
builds the `__getattr__`/`__dir__` pair for such a module from two kinds of
lazy names:

* `exports` - a re-exported object, described as `("home.module", "attr")`
  or as a zero-argument loader, imported/loaded on first access and then
  cached in the module namespace, so every later lookup is a plain attribute
  read;
* `submodules` - the package's own submodules, imported when the attribute
  chain reaches them (`import mcp` then `mcp.client.stdio` used to work as a
  side effect of eager imports; this keeps such chains resolving). Pass the
  set explicitly, or `None` to use the package's real submodules (listed
  once, on first need).

A name that is neither raises `AttributeError` immediately: no filesystem
search and no speculative import on a miss. Callers bind the pair under
`if not TYPE_CHECKING:` so a static type checker never sees a module-level
`__getattr__` (it would type every misspelled attribute as `object` instead of
reporting it) while the mirrored `TYPE_CHECKING` imports keep the real names
typed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from importlib import import_module

__all__ = ["lazy_module_attrs"]

Loader = tuple[str, str] | Callable[[], object]
"""How a lazy export is produced: `("home.module", "attr")` or a zero-arg loader."""

_HELPER_NAMES = frozenset({"__getattr__", "__dir__"})
"""The two functions this helper adds to a module; never reported by its `__dir__`."""

DEFAULT_HIDDEN = frozenset({"TYPE_CHECKING", "_lazy_module_attrs"})
"""The conventional machinery names a caller binds to install the pair (hidden from `dir()`)."""


def lazy_module_attrs(
    module_name: str,
    module_globals: dict[str, object],
    *,
    exports: Mapping[str, Loader] | None = None,
    submodules: frozenset[str] | None = None,
    hidden: frozenset[str] = DEFAULT_HIDDEN,
) -> tuple[Callable[[str], object], Callable[[], list[str]]]:
    """Build a module's `__getattr__` and `__dir__` for lazily-resolved names.

    Args:
        module_name: The `__name__` of the module the pair is installed on.
        module_globals: That module's `globals()`; resolved exports are cached
            in it, so `__getattr__` runs at most once per name.
        exports: Lazy re-exports, name -> `("home.module", "attr")` or a
            zero-argument loader. Resolved on first access.
        submodules: Submodule names reachable as attributes without an
            explicit import. `None` (the default) means the package's real
            submodules, discovered once on first need; a frozenset (possibly
            empty) means exactly those.
        hidden: Namespace entries that are lazy-loading machinery and must not
            appear in `dir(module)` (defaults to the two conventional binding
            names, `TYPE_CHECKING` and `_lazy_module_attrs`).

    Returns:
        The `(__getattr__, __dir__)` pair to bind in the module namespace.
    """
    export_map: Mapping[str, Loader] = exports or {}
    known_submodules = submodules

    def submodule_names() -> frozenset[str]:
        # An explicit set, or the real submodules of the package (one directory
        # listing, cached; dunder entries such as `__main__` are not attributes).
        # A plain module (no `__path__`) has no submodules.
        nonlocal known_submodules
        if known_submodules is None:
            # pkgutil is imported for the one listing rather than at module top,
            # keeping this helper (and so a bare `import mcp`) as light as possible.
            import pkgutil

            search_path = getattr(sys.modules[module_name], "__path__", None)
            known_submodules = frozenset(
                info.name
                for info in (pkgutil.iter_modules(search_path) if search_path else ())
                if not info.name.startswith("__")
            )
        return known_submodules

    def __getattr__(name: str) -> object:
        loader = export_map.get(name)
        if loader is not None:
            if callable(loader):
                value = loader()
            else:
                home_module, attr = loader
                value = getattr(import_module(home_module), attr)
        elif not name.startswith("__") and name in submodule_names():
            # The import system also binds the submodule on the package, so
            # this too runs at most once per name.
            value = import_module(f"{module_name}.{name}")
        else:
            raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
        module_globals[name] = value  # cache: later accesses never reach __getattr__
        return value

    def __dir__() -> list[str]:
        return sorted((module_globals.keys() - hidden - _HELPER_NAMES) | export_map.keys() | submodule_names())

    return __getattr__, __dir__
