from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

# `mcp.shared.<submodule>` (exceptions, memory, message, ...) resolves by
# attribute access even before that submodule was imported. Runtime only,
# so a type checker still flags a misspelled `mcp.shared.<name>`.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals())
