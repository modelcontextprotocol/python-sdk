"""A package that installs `submodule_getattr`, for tests/shared/test_lazy_submodules.py."""

from mcp.shared._lazy_submodules import submodule_getattr

__getattr__ = submodule_getattr(__name__)
