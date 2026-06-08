"""Tests for the `httpx` → `httpx2` migration shim in `mcp.shared._httpx`.

`mcp` prefers `httpx2` and falls back to `httpx` with an `MCPDeprecationWarning` emitted at
the shim's import time. The lockfile pins `httpx` (not `httpx2`), so the canonical state of
the shim is the fallback path.
"""

from __future__ import annotations

import importlib
import warnings
from unittest import mock

import pytest

import mcp.shared._httpx
from mcp.shared.exceptions import MCPDeprecationWarning


@pytest.fixture(autouse=True)
def _restore_shim_state():
    """Reload the shim after each test so a simulated `httpx2` doesn't leak into later tests."""
    yield
    importlib.reload(mcp.shared._httpx)


def test_fallback_emits_warning() -> None:
    with mock.patch.dict("sys.modules", {"httpx2": None}):
        with pytest.warns(MCPDeprecationWarning, match=r"install `httpx2` instead"):
            importlib.reload(mcp.shared._httpx)


def test_httpx2_present_is_silent() -> None:
    import httpx

    with mock.patch.dict("sys.modules", {"httpx2": httpx}):
        with warnings.catch_warnings():
            warnings.simplefilter("error", MCPDeprecationWarning)
            importlib.reload(mcp.shared._httpx)
        assert mcp.shared._httpx.httpx is httpx
