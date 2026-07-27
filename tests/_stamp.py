"""Shared helper: strip the 2026-era serverInfo `_meta` stamp from a result.

Servers stamp `io.modelcontextprotocol/serverInfo` into every 2026-era
result's `_meta` and never into handshake-era ones. Suites whose expected
payloads should stay identity-free strip the stamp before exact comparison -
and the strip is strict, so a modern result that lost its stamp fails the
test instead of passing silently.

The interaction matrix does not use this function directly: its `unstamped`
fixture (tests/interaction/conftest.py) resolves per cell to this strict
strip on modern cells and to a must-not-be-stamped assertion on
handshake-era cells, so one comparison line enforces both eras.
"""

from typing import Any, Protocol, TypeVar

from mcp_types import SERVER_INFO_META_KEY, Result

R = TypeVar("R", bound=Result)


class Unstamp(Protocol):
    """An era-appropriate stamp normalizer: strips or forbids the stamp."""

    def __call__(self, result: R) -> R: ...


def unstamped(result: R) -> R:
    """Assert the result carries a well-formed serverInfo stamp, then remove it.

    Returns the result for inline use in comparisons. Use only where a stamp
    is required (a 2026-era result); the interaction matrix's `unstamped`
    fixture handles the era split.
    """
    meta = result.meta
    assert meta is not None and SERVER_INFO_META_KEY in meta, "expected a serverInfo stamp on this result"
    stamp: Any = meta.pop(SERVER_INFO_META_KEY)
    assert isinstance(stamp, dict)
    assert "name" in stamp and "version" in stamp
    if not meta:
        result.meta = None
    return result
