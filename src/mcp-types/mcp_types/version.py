"""Protocol-version registry and comparison helpers.

Versions are an enumerated set, not an ordered scalar: future identifiers may
not be date-shaped, and unrecognized peer strings must compare conservatively
(lexicographic comparison would put "zzz" above "2025-11-25"). All ordering
goes through KNOWN_PROTOCOL_VERSIONS.
"""

from typing import Final

KNOWN_PROTOCOL_VERSIONS: Final[tuple[str, ...]] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
)
"""Every released protocol revision, oldest to newest."""

HANDSHAKE_PROTOCOL_VERSIONS: Final[tuple[str, ...]] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
"""Protocol revisions reachable via the initialize handshake."""

MODERN_PROTOCOL_VERSIONS: Final[tuple[str, ...]] = ("2026-07-28",)
"""Protocol revisions that use the stateless per-request envelope."""

SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (*HANDSHAKE_PROTOCOL_VERSIONS, *MODERN_PROTOCOL_VERSIONS)
"""Deprecated: use HANDSHAKE_PROTOCOL_VERSIONS or MODERN_PROTOCOL_VERSIONS; kept as their union for v1.x compat."""

LATEST_PROTOCOL_VERSION: Final[str] = KNOWN_PROTOCOL_VERSIONS[-1]
"""Newest protocol revision this SDK speaks (any era)."""

LATEST_HANDSHAKE_VERSION: Final[str] = HANDSHAKE_PROTOCOL_VERSIONS[-1]
"""Newest revision reachable via the `initialize` handshake; the client's offer and server's counter-offer default."""

LATEST_MODERN_VERSION: Final[str] = MODERN_PROTOCOL_VERSIONS[-1]
"""Newest per-request-envelope revision; the `server/discover` probe default."""

OLDEST_SUPPORTED_VERSION: Final[str] = HANDSHAKE_PROTOCOL_VERSIONS[0]
"""Oldest revision this SDK still negotiates via the `initialize` handshake."""


def is_version_at_least(version: str, minimum: str) -> bool:
    """Return True if `version` is a known revision at least as new as `minimum`.

    Unknown `version` strings return False (unrecognized peers compare conservatively).
    `minimum` must be in KNOWN_PROTOCOL_VERSIONS; anything else raises ValueError.
    """
    if minimum not in KNOWN_PROTOCOL_VERSIONS:
        raise ValueError(f"minimum must be a known protocol version, got {minimum!r}")
    if version not in KNOWN_PROTOCOL_VERSIONS:
        return False
    return KNOWN_PROTOCOL_VERSIONS.index(version) >= KNOWN_PROTOCOL_VERSIONS.index(minimum)
