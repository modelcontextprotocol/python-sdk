from __future__ import annotations as _annotations

import warnings
from typing import TypeVar

from mcp.blocks.base import Block

"""Block registry utilities for the MCP Python SDK.

This module provides a minimal—but extensible—mechanism for third-party
packages to register custom *Block* implementations with the core SDK.  The
registry exposes two public helper functions—:func:`register_block` and
:func:`get_block_class`—which allow downstream libraries to add new block
"kinds" and retrieve them at runtime, respectively.

The design is intentionally lightweight:

* The registry is just an in-memory ``dict`` mapping *kind* strings to Python
  classes.
* Registration is performed via a decorator for ergonomic usage on the block
  class definition::

      from mcp.blocks.registry import register_block

      @register_block("my-cool-block")
      class MyBlock(Block):
          ...

* The registry is populated for built-in block types when
  ``mcp.blocks.__init__`` is imported.  Third-party packages can import
  ``mcp.blocks.registry`` at import-time (or call :func:`register_block` during
  plugin initialization) to extend the mapping.

* Thread-safety: Mutating a ``dict`` is atomic in CPython, so casual concurrent
  registration *should* be safe.  However, if your application registers block
  types from multiple threads, you may still wish to provide an external lock
  to coordinate access during import time.

"""

__all__ = [
    "register_block",
    "get_block_class",
    "list_block_kinds",
    "is_block_kind_registered",
    "UnknownBlockKindError",
]

_BlockT = TypeVar("_BlockT", bound=Block)

# NOTE: keep registry private — public API is via helper functions.
_BLOCK_REGISTRY: dict[str, type[Block]] = {}


def register_block(kind: str):  # noqa: D401
    """Return a decorator that registers *cls* under *kind* and yields it back.

    The primary call-site is as a class decorator.  The function also supports
    direct invocation for dynamic registration::

        MyBlock = create_block_cls()
        register_block("my-block")(MyBlock)

    If *kind* is already present, the previous entry will be silently
    overwritten—mirroring Python's module import semantics.  Duplicate kinds
    are thus the caller's responsibility.
    """

    def _inner(cls: type[_BlockT]) -> type[_BlockT]:
        if kind in _BLOCK_REGISTRY:
            warnings.warn(
                f"Block kind {kind!r} is already registered and will be "
                "overwritten.",
                RuntimeWarning,
                stacklevel=2,
            )
        _BLOCK_REGISTRY[kind] = cls
        # Intentionally do *not* mutate the class object beyond registration to
        # keep the hook minimal and avoid leaking extra attributes into user
        # classes.  Downstream packages can attach helpers if they need them.
        return cls

    return _inner


def get_block_class(kind: str) -> type[Block]:
    """Return the class registered for *kind*.

    Raises
    ------
    KeyError
        If *kind* has not been registered (either built-in or via
        :func:`register_block`).
    """

    try:
        return _BLOCK_REGISTRY[kind]
    except KeyError as exc:
        # Re-raise as a more specific exception while preserving backward
        # compatibility with ``except KeyError`` clauses.
        raise UnknownBlockKindError(kind) from exc


# === Public utility helpers ==================================================


def list_block_kinds() -> list[str]:  # noqa: D401
    """Return a *copy* of all currently registered block *kind* strings.

    The returned list is a snapshot—mutating it will **not** affect the global
    registry.  The order of kinds is implementation-defined and should not be
    relied upon.
    """

    return list(_BLOCK_REGISTRY.keys())


def is_block_kind_registered(kind: str) -> bool:  # noqa: D401
    """Return ``True`` if *kind* is currently registered.

    This is equivalent to ``kind in list_block_kinds()`` but avoids the
    intermediate list allocation.
    """

    return kind in _BLOCK_REGISTRY


# === Exceptions ==============================================================


class UnknownBlockKindError(KeyError):
    """Raised when :func:`get_block_class` is called with an unregistered kind.

    Subclasses :class:`KeyError` for backward-compatibility so that existing
    `except KeyError:` handlers continue to work while allowing callers to catch
    this more specific error.
    """

    def __init__(self, kind: str):
        super().__init__(kind)
