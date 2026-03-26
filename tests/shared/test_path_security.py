"""Tests for filesystem path safety primitives."""

from pathlib import Path

import pytest

from mcp.shared.path_security import (
    PathEscapeError,
    contains_path_traversal,
    is_absolute_path,
    safe_join,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Safe: no traversal
        ("a/b/c", False),
        ("readme.txt", False),
        ("", False),
        (".", False),
        ("./a/b", False),
        # Safe: .. balanced by prior descent
        ("a/../b", False),
        ("a/b/../c", False),
        ("a/b/../../c", False),
        # Unsafe: net escape
        ("..", True),
        ("../etc", True),
        ("../../etc/passwd", True),
        ("a/../../b", True),
        ("./../../etc", True),
        # .. as substring, not component — safe
        ("1.0..2.0", False),
        ("foo..bar", False),
        ("..foo", False),
        ("foo..", False),
        # Backslash separator
        ("..\\etc", True),
        ("a\\..\\..\\b", True),
        ("a\\b\\c", False),
        # Mixed separators
        ("a/..\\..\\b", True),
    ],
)
def test_contains_path_traversal(value: str, expected: bool):
    assert contains_path_traversal(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Relative
        ("relative/path", False),
        ("file.txt", False),
        ("", False),
        (".", False),
        ("..", False),
        # POSIX absolute
        ("/", True),
        ("/etc/passwd", True),
        ("/a", True),
        # Windows drive
        ("C:", True),
        ("C:\\Windows", True),
        ("c:/foo", True),
        ("Z:\\", True),
        # Windows UNC / backslash-absolute
        ("\\\\server\\share", True),
        ("\\foo", True),
        # Not a drive: digit before colon
        ("1:foo", False),
        # Colon not in position 1
        ("ab:c", False),
    ],
)
def test_is_absolute_path(value: str, expected: bool):
    assert is_absolute_path(value) is expected


def test_safe_join_simple(tmp_path: Path):
    result = safe_join(tmp_path, "docs", "readme.txt")
    assert result == tmp_path / "docs" / "readme.txt"


def test_safe_join_resolves_relative_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    result = safe_join(".", "file.txt")
    assert result == tmp_path / "file.txt"


def test_safe_join_rejects_dotdot_escape(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="escapes base"):
        safe_join(tmp_path, "../../../etc/passwd")


def test_safe_join_rejects_balanced_then_escape(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="escapes base"):
        safe_join(tmp_path, "a/../../etc")


def test_safe_join_allows_balanced_dotdot(tmp_path: Path):
    result = safe_join(tmp_path, "a/../b")
    assert result == tmp_path / "b"


def test_safe_join_rejects_absolute_part(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="is absolute"):
        safe_join(tmp_path, "/etc/passwd")


def test_safe_join_rejects_absolute_in_later_part(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="is absolute"):
        safe_join(tmp_path, "docs", "/etc/passwd")


def test_safe_join_rejects_windows_drive(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="is absolute"):
        safe_join(tmp_path, "C:\\Windows\\System32")


def test_safe_join_rejects_null_byte(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="null byte"):
        safe_join(tmp_path, "file\0.txt")


def test_safe_join_rejects_null_byte_in_later_part(tmp_path: Path):
    with pytest.raises(PathEscapeError, match="null byte"):
        safe_join(tmp_path, "docs", "file\0.txt")


def test_safe_join_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "escape").symlink_to(outside)

    with pytest.raises(PathEscapeError, match="escapes base"):
        safe_join(sandbox, "escape", "secret.txt")


def test_safe_join_base_equals_target(tmp_path: Path):
    # Joining nothing (or ".") should return the base itself
    assert safe_join(tmp_path) == tmp_path
    assert safe_join(tmp_path, ".") == tmp_path


def test_path_escape_error_is_value_error():
    with pytest.raises(ValueError):
        safe_join("/tmp", "/etc")
