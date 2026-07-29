from mcp.shared._lazy_submodules import submodule_getattr as _submodule_getattr

# `mcp.shared.<submodule>` (exceptions, memory, message, ...) resolves by
# attribute access even before that submodule was imported.
__getattr__ = _submodule_getattr(__name__)
