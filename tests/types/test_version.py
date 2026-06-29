import pytest
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    KNOWN_PROTOCOL_VERSIONS,
    MODERN_PROTOCOL_VERSIONS,
    is_version_at_least,
)


@pytest.mark.parametrize(
    ("version", "minimum", "expected"),
    [
        ("2025-11-25", "2025-11-25", True),
        ("2024-11-05", "2024-11-05", True),
        ("2025-11-25", "2025-06-18", True),
        ("2025-06-18", "2024-11-05", True),
        ("2025-06-18", "2025-11-25", False),
        ("2024-11-05", "2025-03-26", False),
    ],
)
def test_is_version_at_least_ordering(version: str, minimum: str, expected: bool) -> None:
    assert is_version_at_least(version, minimum) is expected


@pytest.mark.parametrize("version", ["zzz", "", "2025-11-26", "draft", "9999-99-99"])
def test_is_version_at_least_unknown_version_is_false(version: str) -> None:
    assert is_version_at_least(version, "2024-11-05") is False


def test_is_version_at_least_unknown_minimum_raises() -> None:
    """An unknown minimum is programmer error, not peer input."""
    with pytest.raises(ValueError, match="zzz"):
        is_version_at_least("2025-11-25", "zzz")


@pytest.mark.parametrize(
    ("version", "minimum"), [(v, m) for v in KNOWN_PROTOCOL_VERSIONS for m in KNOWN_PROTOCOL_VERSIONS]
)
def test_is_version_at_least_matches_lexicographic_for_known_versions(version: str, minimum: str) -> None:
    """Pins equivalence with the plain string comparison the helper replaced."""
    assert is_version_at_least(version, minimum) is (version >= minimum)


def test_supported_versions_are_known() -> None:
    assert set(HANDSHAKE_PROTOCOL_VERSIONS) <= set(KNOWN_PROTOCOL_VERSIONS)
    assert set(MODERN_PROTOCOL_VERSIONS) <= set(KNOWN_PROTOCOL_VERSIONS)


def test_known_versions_are_strictly_ordered() -> None:
    assert list(KNOWN_PROTOCOL_VERSIONS) == sorted(set(KNOWN_PROTOCOL_VERSIONS))
