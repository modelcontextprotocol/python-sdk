"""Shared helper: drop the 2026-era serverInfo `_meta` stamp from a result.

Servers stamp `io.modelcontextprotocol/serverInfo` into every 2026-era
result's `_meta` and never into handshake-era ones, and the stamp's `version`
defaults to the installed package version. Suites that share one expected
payload across eras (the interaction matrix) or that construct servers
without a pinned version strip the stamp before exact comparison. Stamp
semantics themselves have dedicated coverage in tests/server/test_runner.py.
"""

from typing import Any, TypeVar

from mcp_types import SERVER_INFO_META_KEY, Result

R = TypeVar("R", bound=Result)


def unstamped(result: R) -> R:
    """Remove the serverInfo stamp in place if present, asserting its shape.

    Present-versus-absent is era-dependent and belongs to the runner tests;
    this only guarantees that when a stamp exists it is a well-formed
    identity object, then returns the result for inline use in comparisons.
    """
    meta = result.meta
    if meta is not None and SERVER_INFO_META_KEY in meta:
        stamp: Any = meta.pop(SERVER_INFO_META_KEY)
        assert isinstance(stamp, dict)
        assert "name" in stamp and "version" in stamp
        if not meta:
            result.meta = None
    return result
