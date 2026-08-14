"""A package that installs the lazy-attribute helper, for tests/shared/test_lazy.py."""

from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

load_calls: int = 0

if TYPE_CHECKING:
    # Type checkers see the lazy export as a plain module attribute.
    ANSWER: int


def _load_answer() -> int:
    """A lazily-resolved re-export: a zero-argument loader that must run at most once."""
    global load_calls
    load_calls += 1
    return 42


if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals(), exports={"ANSWER": _load_answer})
