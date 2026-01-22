"""Tests for tool name validation utilities (SEP-986)."""

import logging

import pytest

from mcp.shared.tool_name_validation import (
    issue_tool_name_warning,
    validate_and_warn_tool_name,
    validate_tool_name,
)


class TestValidateToolName:
    """Tests for validate_tool_name function."""

    class TestValidNames:
        """Test cases for valid tool names."""

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
        def test_accepts_valid_names(self, tool_name: str) -> None:
            """Valid tool names should pass validation with no warnings."""
            result = validate_tool_name(tool_name)
            assert result.is_valid is True
            assert result.warnings == []

    class TestInvalidNames:
        """Test cases for invalid tool names."""

        def test_rejects_empty_name(self) -> None:
            """Empty names should be rejected."""
            result = validate_tool_name("")
            assert result.is_valid is False
            assert "Tool name cannot be empty" in result.warnings

        def test_rejects_name_exceeding_max_length(self) -> None:
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
        def test_rejects_invalid_characters(self, tool_name: str, expected_char: str) -> None:
            """Names with invalid characters should be rejected."""
            result = validate_tool_name(tool_name)
            assert result.is_valid is False
            assert any("invalid characters" in w and expected_char in w for w in result.warnings)

        def test_rejects_multiple_invalid_chars(self) -> None:
            """Names with multiple invalid chars should list all of them."""
            result = validate_tool_name("user name@domain,com")
            assert result.is_valid is False
            warning = next(w for w in result.warnings if "invalid characters" in w)
            assert "' '" in warning
            assert "'@'" in warning
            assert "','" in warning

        def test_rejects_unicode_characters(self) -> None:
            """Names with unicode characters should be rejected."""
            result = validate_tool_name("user-\u00f1ame")  # n with tilde
            assert result.is_valid is False

    class TestWarningsForProblematicPatterns:
        """Test cases for valid names that generate warnings."""

        def test_warns_on_leading_dash(self) -> None:
            """Names starting with dash should generate warning but be valid."""
            result = validate_tool_name("-get-user")
            assert result.is_valid is True
            assert any("starts or ends with a dash" in w for w in result.warnings)

        def test_warns_on_trailing_dash(self) -> None:
            """Names ending with dash should generate warning but be valid."""
            result = validate_tool_name("get-user-")
            assert result.is_valid is True
            assert any("starts or ends with a dash" in w for w in result.warnings)

        def test_warns_on_leading_dot(self) -> None:
            """Names starting with dot should generate warning but be valid."""
            result = validate_tool_name(".get.user")
            assert result.is_valid is True
            assert any("starts or ends with a dot" in w for w in result.warnings)

        def test_warns_on_trailing_dot(self) -> None:
            """Names ending with dot should generate warning but be valid."""
            result = validate_tool_name("get.user.")
            assert result.is_valid is True
            assert any("starts or ends with a dot" in w for w in result.warnings)


class TestIssueToolNameWarning:
    """Tests for issue_tool_name_warning function."""

    def test_logs_warnings(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warnings should be logged at WARNING level."""
        warnings = ["Warning 1", "Warning 2"]
        with caplog.at_level(logging.WARNING):
            issue_tool_name_warning("test-tool", warnings)

        assert 'Tool name validation warning for "test-tool"' in caplog.text
        assert "- Warning 1" in caplog.text
        assert "- Warning 2" in caplog.text
        assert "Tool registration will proceed" in caplog.text
        assert "SEP-986" in caplog.text

    def test_no_logging_for_empty_warnings(self, caplog: pytest.LogCaptureFixture) -> None:
        """Empty warnings list should not produce any log output."""
        with caplog.at_level(logging.WARNING):
            issue_tool_name_warning("test-tool", [])

        assert caplog.text == ""


class TestValidateAndWarnToolName:
    """Tests for validate_and_warn_tool_name function."""

    def test_returns_true_for_valid_name(self) -> None:
        """Valid names should return True."""
        assert validate_and_warn_tool_name("valid-tool-name") is True

    def test_returns_false_for_invalid_name(self) -> None:
        """Invalid names should return False."""
        assert validate_and_warn_tool_name("") is False
        assert validate_and_warn_tool_name("a" * 129) is False
        assert validate_and_warn_tool_name("invalid name") is False

    def test_logs_warnings_for_invalid_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """Invalid names should trigger warning logs."""
        with caplog.at_level(logging.WARNING):
            validate_and_warn_tool_name("invalid name")

        assert "Tool name validation warning" in caplog.text

    def test_no_warnings_for_clean_valid_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """Clean valid names should not produce any log output."""
        with caplog.at_level(logging.WARNING):
            result = validate_and_warn_tool_name("clean-tool-name")

        assert result is True
        assert caplog.text == ""


class TestEdgeCases:
    """Test edge cases and robustness."""

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
    def test_edge_cases(self, tool_name: str, is_valid: bool, expected_warning_fragment: str) -> None:
        """Various edge cases should be handled correctly."""
        result = validate_tool_name(tool_name)
        assert result.is_valid is is_valid
        assert any(expected_warning_fragment in w for w in result.warnings)
