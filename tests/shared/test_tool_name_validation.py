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
        # a single trailing newline slipped past `$` with re.match
        ("valid_name\n", "'\\n'"),
        ("a" * 127 + "\n", "'\\n'"),
    ],
    ids=[
        "with_spaces",
        "with_commas",
        "with_slashes",
        "with_at_symbol",
        "with_trailing_newline",
        "max_length_with_trailing_newline",
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


# ============================================================================
# NEW TESTS: Unicode Homoglyph & Confusable Character Detection
# ============================================================================
# These tests verify that the validator detects Unicode homoglyphs
# (characters that look identical but are different) that could be used
# for tool name spoofing attacks.


class TestUnicodeHomoglyphDetection:
    """Tests for detecting Unicode homoglyphs that visually impersonate ASCII."""

    def test_cyrillic_a_rejected(self) -> None:
        """Cyrillic А (U+0410) looks identical to Latin A but must be rejected.

        Note: NFKC does not map Cyrillic to Latin lookalikes, so this character
        is caught by the ASCII-only regex check (invalid characters), not by the
        normalization check. The rejection is the important invariant here.
        """
        result = validate_tool_name("tool_А")
        assert not result.is_valid, "Cyrillic А should be rejected"
        assert any("invalid characters" in w.lower() for w in result.warnings), (
            f"Expected invalid-character warning. Got: {result.warnings}"
        )

    def test_cyrillic_o_rejected(self) -> None:
        """Cyrillic О (U+041E) looks identical to Latin O."""
        result = validate_tool_name("tool_О")
        assert not result.is_valid

    def test_cyrillic_e_rejected(self) -> None:
        """Cyrillic Е (U+0415) looks identical to Latin E."""
        result = validate_tool_name("tool_Е")
        assert not result.is_valid

    def test_cyrillic_p_rejected(self) -> None:
        """Cyrillic Р (U+0420) looks identical to Latin P."""
        result = validate_tool_name("tool_Р")
        assert not result.is_valid

    def test_fullwidth_a_rejected(self) -> None:
        """Fullwidth Latin а (U+FF41) looks like ASCII a."""
        result = validate_tool_name("ａtool")
        assert not result.is_valid

    def test_fullwidth_mixed_rejected(self) -> None:
        """Mix of fullwidth and ASCII should be detected."""
        result = validate_tool_name("toｏl")  # 'о' is fullwidth
        assert not result.is_valid

    def test_greek_alpha_rejected(self) -> None:
        """Greek Α (U+0391) looks like Latin A."""
        result = validate_tool_name("tool_Α")
        assert not result.is_valid

    def test_rtl_override_rejected(self) -> None:
        """Right-to-left override character (U+202E) should be rejected."""
        result = validate_tool_name("tool‮_name")  # RIGHT-TO-LEFT OVERRIDE
        assert not result.is_valid
        assert any("directional" in w.lower() or "rtl" in w.lower() for w in result.warnings), (
            f"Warning should mention directional formatting. Got: {result.warnings}"
        )

    def test_ltr_override_rejected(self) -> None:
        """Left-to-right override character (U+202D) should be rejected."""
        result = validate_tool_name("tool‭_name")  # LEFT-TO-RIGHT OVERRIDE
        assert not result.is_valid


class TestUnicodeNormalizationBypass:
    """Tests for Unicode normalization form attacks."""

    def test_decomposed_unicode_detected(self) -> None:
        """Decomposed Unicode should be normalized and detected."""
        import unicodedata

        # 'café' in decomposed form (e + combining accent)
        decomposed = unicodedata.normalize("NFD", "café")
        result = validate_tool_name(f"tool_{decomposed}")
        # Should either be rejected or warn
        assert not result.is_valid or any("normalize" in w.lower() for w in result.warnings), (
            f"Decomposed forms should be detected. Got is_valid={result.is_valid}, warnings={result.warnings}"
        )

    def test_nfkc_normalization_detected(self) -> None:
        """NFKC normalization changes should be detected.

        Fullwidth ASCII (e.g. ａｂｃ) always normalizes under NFKC, so the
        validator must flag it unconditionally.
        """
        # Fullwidth characters always normalize to ASCII under NFKC
        original = "ａｂｃ"  # Fullwidth ASCII — NFKC maps these to 'abc'
        result = validate_tool_name(original)
        assert not result.is_valid or any("normalize" in w.lower() for w in result.warnings), (
            "NFKC normalization should be detected"
        )


class TestUnicodeBoundaryConditions:
    """Edge cases and boundary conditions."""

    def test_zero_width_characters_rejected(self) -> None:
        """Zero-width characters should be rejected."""
        result = validate_tool_name("tool​_name")  # Zero-width space
        assert not result.is_valid


class TestValidAsciiStillWorks:
    """Ensure valid ASCII tool names still pass after homoglyph detection added."""

    def test_basic_ascii_passes(self) -> None:
        """Standard ASCII tool names should still pass."""
        result = validate_tool_name("verify_user")
        assert result.is_valid

    def test_numbers_pass(self) -> None:
        result = validate_tool_name("tool_123")
        assert result.is_valid

    def test_dashes_underscores_pass(self) -> None:
        result = validate_tool_name("my-tool_name-v2")
        assert result.is_valid

    def test_dots_pass(self) -> None:
        result = validate_tool_name("tool.extension")
        assert result.is_valid

    def test_long_valid_name_passes(self) -> None:
        result = validate_tool_name("a" * 128)  # Max length, all valid
        assert result.is_valid
