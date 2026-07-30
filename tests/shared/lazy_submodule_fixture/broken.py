"""A submodule whose own import fails on a missing dependency."""

from importlib import import_module

MARKER = import_module("definitely_not_installed_dependency_xyz")
