"""Protocol-version registry and comparison/classification helpers.

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
    "2026-07-28",  # draft: recognized for ordering/classification, NOT negotiable
)
"""Every protocol revision this SDK knows about, oldest to newest."""

DRAFT_PROTOCOL_VERSION: Final[str] = "2026-07-28"
"""The in-progress spec revision.

Recognized by the helpers in this module but absent from
SUPPORTED_PROTOCOL_VERSIONS until the SDK actually implements it.
"""

SUPPORTED_PROTOCOL_VERSIONS: list[str] = ["2024-11-05", "2025-03-26", "2025-06-18", LATEST_PROTOCOL_VERSION]
"""Protocol revisions this SDK can negotiate."""

STATEFUL_PROTOCOL_VERSIONS: Final[frozenset[str]] = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})
"""Revisions that negotiate via the initialize handshake.

Closed by design: every revision after 2025-11-25 is stateless and negotiates
per-request, never via initialize. Hardcoded - do not derive from
SUPPORTED_PROTOCOL_VERSIONS. (Matches typescript-sdk's
STATEFUL_PROTOCOL_VERSIONS / isStatefulProtocolVersion.)
"""


def is_stateful_protocol_version(version: str) -> bool:
    """Return True if `version` negotiates via the initialize handshake."""
    return version in STATEFUL_PROTOCOL_VERSIONS


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
