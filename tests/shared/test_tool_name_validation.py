"""Tests for tool name validation utilities (SEP-986)."""

import logging

import pytest

from mcp.shared.tool_name_validation import (
    issue_tool_name_warning,
    validate_and_warn_tool_name,
    validate_tool_name,
)

# Tests for validate_tool_name function - valid names


@pytest.mark.parametrize(
    "tool_name",
    [
        "getUser",
        "get_user_profile",
        "user-profile-update",
        "admin.tools.list",
        "DATA_EXPORT_v2.1",
        "a",
        "a" * 128,
    ],
    ids=[
        "simple_alphanumeric",
        "with_underscores",
        "with_dashes",
        "with_dots",
        "mixed_characters",
        "single_character",
        "max_length_128",
    ],
)
def test_validate_tool_name_accepts_valid_names(tool_name: str) -> None:
    """Valid tool names should pass validation with no warnings."""
    result = validate_tool_name(tool_name)
    assert result.is_valid is True
    assert result.warnings == []


# Tests for validate_tool_name function - invalid names


def test_validate_tool_name_rejects_empty_name() -> None:
    """Empty names should be rejected."""
    result = validate_tool_name("")
    assert result.is_valid is False
    assert "Tool name cannot be empty" in result.warnings


def test_validate_tool_name_rejects_name_exceeding_max_length() -> None:
    """Names exceeding 128 characters should be rejected."""
    result = validate_tool_name("a" * 129)
    assert result.is_valid is False
    assert any("exceeds maximum length of 128 characters (current: 129)" in w for w in result.warnings)


@pytest.mark.parametrize(
    "tool_name,expected_char",
    [
        ("get user profile", "' '"),
        ("get,user,profile", "','"),
        ("user/profile/update", "'/'"),
        ("user@domain.com", "'@'"),
    ],
    ids=[
        "with_spaces",
        "with_commas",
        "with_slashes",
        "with_at_symbol",
    ],
)
def test_validate_tool_name_rejects_invalid_characters(tool_name: str, expected_char: str) -> None:
    """Names with invalid characters should be rejected."""
    result = validate_tool_name(tool_name)
    assert result.is_valid is False
    assert any("invalid characters" in w and expected_char in w for w in result.warnings)


def test_validate_tool_name_rejects_multiple_invalid_chars() -> None:
    """Names with multiple invalid chars should list all of them."""
    result = validate_tool_name("user name@domain,com")
    assert result.is_valid is False
    warning = next(w for w in result.warnings if "invalid characters" in w)
    assert "' '" in warning
    assert "'@'" in warning
    assert "','" in warning


def test_validate_tool_name_rejects_unicode_characters() -> None:
    """Names with unicode characters should be rejected."""
    result = validate_tool_name("user-\u00f1ame")  # n with tilde
    assert result.is_valid is False


# Tests for validate_tool_name function - warnings for problematic patterns


def test_validate_tool_name_warns_on_leading_dash() -> None:
    """Names starting with dash should generate warning but be valid."""
    result = validate_tool_name("-get-user")
    assert result.is_valid is True
    assert any("starts or ends with a dash" in w for w in result.warnings)


def test_validate_tool_name_warns_on_trailing_dash() -> None:
    """Names ending with dash should generate warning but be valid."""
    result = validate_tool_name("get-user-")
    assert result.is_valid is True
    assert any("starts or ends with a dash" in w for w in result.warnings)


def test_validate_tool_name_warns_on_leading_dot() -> None:
    """Names starting with dot should generate warning but be valid."""
    result = validate_tool_name(".get.user")
    assert result.is_valid is True
    assert any("starts or ends with a dot" in w for w in result.warnings)


def test_validate_tool_name_warns_on_trailing_dot() -> None:
    """Names ending with dot should generate warning but be valid."""
    result = validate_tool_name("get.user.")
    assert result.is_valid is True
    assert any("starts or ends with a dot" in w for w in result.warnings)


# Tests for issue_tool_name_warning function


def test_issue_tool_name_warning_logs_warnings(caplog: pytest.LogCaptureFixture) -> None:
    """Warnings should be logged at WARNING level."""
    warnings = ["Warning 1", "Warning 2"]
    with caplog.at_level(logging.WARNING):
        issue_tool_name_warning("test-tool", warnings)

    assert 'Tool name validation warning for "test-tool"' in caplog.text
    assert "- Warning 1" in caplog.text
    assert "- Warning 2" in caplog.text
    assert "Tool registration will proceed" in caplog.text
    assert "SEP-986" in caplog.text


def test_issue_tool_name_warning_no_logging_for_empty_warnings(caplog: pytest.LogCaptureFixture) -> None:
    """Empty warnings list should not produce any log output."""
    with caplog.at_level(logging.WARNING):
        issue_tool_name_warning("test-tool", [])

    assert caplog.text == ""


# Tests for validate_and_warn_tool_name function


def test_validate_and_warn_tool_name_returns_true_for_valid_name() -> None:
    """Valid names should return True."""
    assert validate_and_warn_tool_name("valid-tool-name") is True


def test_validate_and_warn_tool_name_returns_false_for_invalid_name() -> None:
    """Invalid names should return False."""
    assert validate_and_warn_tool_name("") is False
    assert validate_and_warn_tool_name("a" * 129) is False
    assert validate_and_warn_tool_name("invalid name") is False


def test_validate_and_warn_tool_name_logs_warnings_for_invalid_name(caplog: pytest.LogCaptureFixture) -> None:
    """Invalid names should trigger warning logs."""
    with caplog.at_level(logging.WARNING):
        validate_and_warn_tool_name("invalid name")

    assert "Tool name validation warning" in caplog.text


def test_validate_and_warn_tool_name_no_warnings_for_clean_valid_name(caplog: pytest.LogCaptureFixture) -> None:
    """Clean valid names should not produce any log output."""
    with caplog.at_level(logging.WARNING):
        result = validate_and_warn_tool_name("clean-tool-name")

    assert result is True
    assert caplog.text == ""


# Tests for edge cases


@pytest.mark.parametrize(
    "tool_name,is_valid,expected_warning_fragment",
    [
        ("...", True, "starts or ends with a dot"),
        ("---", True, "starts or ends with a dash"),
        ("///", False, "invalid characters"),
        ("user@name123", False, "invalid characters"),
    ],
    ids=[
        "only_dots",
        "only_dashes",
        "only_slashes",
        "mixed_valid_invalid",
    ],
)
def test_edge_cases(tool_name: str, is_valid: bool, expected_warning_fragment: str) -> None:
    """Various edge cases should be handled correctly."""
    result = validate_tool_name(tool_name)
    assert result.is_valid is is_valid
    assert any(expected_warning_fragment in w for w in result.warnings)
