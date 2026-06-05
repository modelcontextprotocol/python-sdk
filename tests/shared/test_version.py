"""Tests for the protocol-version registry and comparison helpers."""

import pytest

from mcp.shared.version import (
    DRAFT_PROTOCOL_VERSION,
    KNOWN_PROTOCOL_VERSIONS,
    STATEFUL_PROTOCOL_VERSIONS,
    SUPPORTED_PROTOCOL_VERSIONS,
    is_stateful_protocol_version,
    is_version_at_least,
)
from mcp.types import LATEST_PROTOCOL_VERSION


@pytest.mark.parametrize(
    ("version", "minimum", "expected"),
    [
        # equal
        ("2025-11-25", "2025-11-25", True),
        ("2024-11-05", "2024-11-05", True),
        # above
        ("2025-11-25", "2025-06-18", True),
        ("2026-07-28", "2024-11-05", True),
        # below
        ("2025-06-18", "2025-11-25", False),
        ("2024-11-05", "2026-07-28", False),
    ],
)
def test_is_version_at_least_ordering(version: str, minimum: str, expected: bool) -> None:
    assert is_version_at_least(version, minimum) is expected


@pytest.mark.parametrize("version", ["zzz", "", "2025-11-26", "draft", "9999-99-99"])
def test_is_version_at_least_unknown_version_is_false(version: str) -> None:
    """Unrecognized peer strings compare conservatively, never accidentally."""
    assert is_version_at_least(version, "2024-11-05") is False


def test_is_version_at_least_unknown_minimum_raises() -> None:
    """An unknown minimum is programmer error, not peer input."""
    with pytest.raises(ValueError, match="zzz"):
        is_version_at_least("2025-11-25", "zzz")


@pytest.mark.parametrize(
    ("version", "minimum"), [(v, m) for v in KNOWN_PROTOCOL_VERSIONS for m in KNOWN_PROTOCOL_VERSIONS]
)
def test_is_version_at_least_matches_lexicographic_for_known_versions(version: str, minimum: str) -> None:
    """Drop-in equivalence: for every known (date-shaped) revision pair the helper
    agrees with the string comparison it replaced."""
    assert is_version_at_least(version, minimum) is (version >= minimum)


def test_draft_version_is_known_but_not_negotiable_and_not_stateful() -> None:
    assert DRAFT_PROTOCOL_VERSION in KNOWN_PROTOCOL_VERSIONS
    assert DRAFT_PROTOCOL_VERSION not in SUPPORTED_PROTOCOL_VERSIONS
    assert not is_stateful_protocol_version(DRAFT_PROTOCOL_VERSION)


def test_draft_version_is_at_least_every_released_version() -> None:
    for released in SUPPORTED_PROTOCOL_VERSIONS:
        assert is_version_at_least(DRAFT_PROTOCOL_VERSION, released)


def test_every_supported_version_is_stateful() -> None:
    for version in SUPPORTED_PROTOCOL_VERSIONS:
        assert is_stateful_protocol_version(version)


def test_supported_versions_are_a_strict_subset_of_known() -> None:
    assert set(SUPPORTED_PROTOCOL_VERSIONS) < set(KNOWN_PROTOCOL_VERSIONS)


def test_latest_version_is_stateful() -> None:
    assert LATEST_PROTOCOL_VERSION in STATEFUL_PROTOCOL_VERSIONS


def test_known_versions_are_strictly_ordered() -> None:
    """The registry tuple is the ordering source of truth: ascending, no duplicates."""
    assert list(KNOWN_PROTOCOL_VERSIONS) == sorted(set(KNOWN_PROTOCOL_VERSIONS))
