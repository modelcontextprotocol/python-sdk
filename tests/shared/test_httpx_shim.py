"""Tests for the `httpx` → `httpx2` migration shim in `mcp.shared._httpx`.

`mcp` prefers `httpx2` and falls back to `httpx` with an `MCPDeprecationWarning`. The
fallback is exercised when only `httpx` is installed (today this is always — `httpx2` is
not yet on PyPI). The warning is emitted once per process from HTTP-touching surfaces.
"""

from __future__ import annotations

import warnings

import pytest

from mcp.shared import _httpx as httpx_shim
from mcp.shared._httpx import MCPDeprecationWarning, emit_httpx_deprecation_warning
from mcp.shared._httpx_utils import create_mcp_http_client

pytestmark = pytest.mark.anyio


@pytest.fixture
def reset_warning_flag(monkeypatch: pytest.MonkeyPatch):
    """Reset the once-per-process flag so each test gets a fresh emission state."""
    monkeypatch.setattr(httpx_shim, "_warning_emitted", False)


def test_emit_warns_when_httpx_is_deprecated(monkeypatch: pytest.MonkeyPatch, reset_warning_flag: None) -> None:
    monkeypatch.setattr(httpx_shim, "_HTTPX_IS_DEPRECATED", True)
    with pytest.warns(MCPDeprecationWarning, match=r"install `httpx2` instead"):
        emit_httpx_deprecation_warning()


def test_emit_silent_when_httpx2_is_used(monkeypatch: pytest.MonkeyPatch, reset_warning_flag: None) -> None:
    monkeypatch.setattr(httpx_shim, "_HTTPX_IS_DEPRECATED", False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", MCPDeprecationWarning)
        emit_httpx_deprecation_warning()
    assert [w for w in caught if issubclass(w.category, MCPDeprecationWarning)] == []


def test_emit_only_warns_once_per_process(monkeypatch: pytest.MonkeyPatch, reset_warning_flag: None) -> None:
    monkeypatch.setattr(httpx_shim, "_HTTPX_IS_DEPRECATED", True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", MCPDeprecationWarning)
        emit_httpx_deprecation_warning()
        emit_httpx_deprecation_warning()
        emit_httpx_deprecation_warning()
    matching = [w for w in caught if issubclass(w.category, MCPDeprecationWarning)]
    assert len(matching) == 1


async def test_create_mcp_http_client_emits_warning(monkeypatch: pytest.MonkeyPatch, reset_warning_flag: None) -> None:
    monkeypatch.setattr(httpx_shim, "_HTTPX_IS_DEPRECATED", True)
    with pytest.warns(MCPDeprecationWarning, match=r"install `httpx2` instead"):
        async with create_mcp_http_client():
            pass


async def test_create_mcp_http_client_silent_with_httpx2(
    monkeypatch: pytest.MonkeyPatch, reset_warning_flag: None
) -> None:
    monkeypatch.setattr(httpx_shim, "_HTTPX_IS_DEPRECATED", False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", MCPDeprecationWarning)
        async with create_mcp_http_client():
            pass
    assert [w for w in caught if issubclass(w.category, MCPDeprecationWarning)] == []


def test_shim_picks_up_httpx2_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aliasing `httpx2` to the installed `httpx` module exercises the preferred import path.

    `mcp`'s lockfile pins `httpx` (not `httpx2`), so the `import httpx2 as httpx` branch is
    otherwise uncovered in CI. This test injects `httpx2` into `sys.modules` and reloads the
    shim to cover that branch deterministically.
    """
    import importlib
    import sys

    import httpx as real_httpx

    monkeypatch.setitem(sys.modules, "httpx2", real_httpx)
    monkeypatch.delitem(sys.modules, "mcp.shared._httpx", raising=False)
    try:
        reloaded = importlib.import_module("mcp.shared._httpx")
        assert reloaded._HTTPX_IS_DEPRECATED is False
        assert reloaded.httpx is real_httpx
    finally:
        # Restore the canonical shim module so subsequent tests see the real state.
        sys.modules.pop("mcp.shared._httpx", None)
        importlib.import_module("mcp.shared._httpx")
