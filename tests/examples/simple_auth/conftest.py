from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def load_example_module() -> Callable[[Path, str], ModuleType]:
    """Import a workspace example without requiring it in the root test environment."""

    def load(package_root: Path, module_name: str) -> ModuleType:
        original_path = sys.path.copy()
        try:
            sys.path.insert(0, str(package_root))
            return importlib.import_module(module_name)
        finally:
            sys.path[:] = original_path

    return load
