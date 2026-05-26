"""Tests for the `httpx` → `httpx2` migration shim in `mcp.shared._httpx`.

`mcp` prefers `httpx2` and falls back to `httpx` with an `MCPDeprecationWarning` emitted at
the shim's import time. Today the lockfile pins `httpx` (not `httpx2`), so importing the shim
exercises the fallback.
"""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest

from mcp.shared._warnings import MCPDeprecationWarning


def _force_reimport_shim() -> None:
    """Drop the cached shim module so the next import re-runs its top-level code."""
    sys.modules.pop("mcp.shared._httpx", None)


def test_fallback_emits_warning_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """With only `httpx` installed, importing the shim emits `MCPDeprecationWarning`."""
    monkeypatch.delitem(sys.modules, "httpx2", raising=False)
    _force_reimport_shim()

    from collections.abc import Mapping, Sequence

    real_import = __import__

    def fake_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "httpx2":
            raise ImportError("simulated: httpx2 not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.warns(MCPDeprecationWarning, match=r"install `httpx2` instead"):
        importlib.import_module("mcp.shared._httpx")


def test_httpx2_present_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `httpx2` is importable, the shim selects it and emits no warning."""
    import httpx as real_httpx

    monkeypatch.setitem(sys.modules, "httpx2", real_httpx)
    _force_reimport_shim()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", MCPDeprecationWarning)
        reloaded = importlib.import_module("mcp.shared._httpx")

    assert reloaded.httpx is real_httpx
    assert [w for w in caught if issubclass(w.category, MCPDeprecationWarning)] == []
