"""Protocol-version registry and comparison helpers.

Date-string protocol revisions happen to sort lexicographically, but versions
are an enumerated set, not an ordered scalar: future identifiers are not
guaranteed to be date-shaped, and unrecognized peer strings must compare
conservatively instead of accidentally (e.g. "zzz" > "2025-11-25"). All
ordering questions go through KNOWN_PROTOCOL_VERSIONS.
"""

from typing import Final

from mcp.types import LATEST_PROTOCOL_VERSION

KNOWN_PROTOCOL_VERSIONS: Final[tuple[str, ...]] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
)
"""Every released protocol revision, oldest to newest."""

SUPPORTED_PROTOCOL_VERSIONS: list[str] = ["2024-11-05", "2025-03-26", "2025-06-18", LATEST_PROTOCOL_VERSION]
"""Protocol revisions this SDK can negotiate."""


def is_version_at_least(version: str, minimum: str) -> bool:
    """Return True if `version` is a known revision at least as new as `minimum`.

    Unknown `version` strings return False (treat unrecognized peers
    conservatively). `minimum` must be a member of KNOWN_PROTOCOL_VERSIONS;
    passing anything else is programmer error and raises ValueError.
    """
    if minimum not in KNOWN_PROTOCOL_VERSIONS:
        raise ValueError(f"minimum must be a known protocol version, got {minimum!r}")
    if version not in KNOWN_PROTOCOL_VERSIONS:
        return False
    return KNOWN_PROTOCOL_VERSIONS.index(version) >= KNOWN_PROTOCOL_VERSIONS.index(minimum)
