"""Tests for MCP exception classes."""

import pytest

from mcp.shared.exceptions import McpError, UrlElicitationRequiredError
from mcp.types import URL_ELICITATION_REQUIRED, ElicitRequestURLParams, ErrorData


class TestUrlElicitationRequiredError:
    """Tests for UrlElicitationRequiredError exception class."""

    def test_create_with_single_elicitation(self) -> None:
        """Test creating error with a single elicitation."""
        elicitation = ElicitRequestURLParams(
            mode="url",
            message="Auth required",
            url="https://example.com/auth",
            elicitationId="test-123",
        )
        error = UrlElicitationRequiredError([elicitation])

        assert error.error.code == URL_ELICITATION_REQUIRED
        assert error.error.message == "URL elicitation required"
        assert len(error.elicitations) == 1
        assert error.elicitations[0].elicitationId == "test-123"

    def test_create_with_multiple_elicitations(self) -> None:
        """Test creating error with multiple elicitations uses plural message."""
        elicitations = [
            ElicitRequestURLParams(
                mode="url",
                message="Auth 1",
                url="https://example.com/auth1",
                elicitationId="test-1",
            ),
            ElicitRequestURLParams(
                mode="url",
                message="Auth 2",
                url="https://example.com/auth2",
                elicitationId="test-2",
            ),
        ]
        error = UrlElicitationRequiredError(elicitations)

        assert error.error.message == "URL elicitations required"  # Plural
        assert len(error.elicitations) == 2

    def test_custom_message(self) -> None:
        """Test creating error with a custom message."""
        elicitation = ElicitRequestURLParams(
            mode="url",
            message="Auth required",
            url="https://example.com/auth",
            elicitationId="test-123",
        )
        error = UrlElicitationRequiredError([elicitation], message="Custom message")

        assert error.error.message == "Custom message"

    def test_from_error_data(self) -> None:
        """Test reconstructing error from ErrorData."""
        error_data = ErrorData(
            code=URL_ELICITATION_REQUIRED,
            message="URL elicitation required",
            data={
                "elicitations": [
                    {
                        "mode": "url",
                        "message": "Auth required",
                        "url": "https://example.com/auth",
                        "elicitationId": "test-123",
                    }
                ]
            },
        )

        error = UrlElicitationRequiredError.from_error(error_data)

        assert len(error.elicitations) == 1
        assert error.elicitations[0].elicitationId == "test-123"
        assert error.elicitations[0].url == "https://example.com/auth"

    def test_from_error_data_wrong_code(self) -> None:
        """Test that from_error raises ValueError for wrong error code."""
        error_data = ErrorData(
            code=-32600,  # Wrong code
            message="Some other error",
            data={},
        )

        with pytest.raises(ValueError, match="Expected error code"):
            UrlElicitationRequiredError.from_error(error_data)

    def test_serialization_roundtrip(self) -> None:
        """Test that error can be serialized and reconstructed."""
        original = UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    mode="url",
                    message="Auth required",
                    url="https://example.com/auth",
                    elicitationId="test-123",
                )
            ]
        )

        # Simulate serialization over wire
        error_data = original.error

        # Reconstruct
        reconstructed = UrlElicitationRequiredError.from_error(error_data)

        assert reconstructed.elicitations[0].elicitationId == original.elicitations[0].elicitationId
        assert reconstructed.elicitations[0].url == original.elicitations[0].url
        assert reconstructed.elicitations[0].message == original.elicitations[0].message

    def test_error_data_contains_elicitations(self) -> None:
        """Test that error data contains properly serialized elicitations."""
        elicitation = ElicitRequestURLParams(
            mode="url",
            message="Please authenticate",
            url="https://example.com/oauth",
            elicitationId="oauth-flow-1",
        )
        error = UrlElicitationRequiredError([elicitation])

        assert error.error.data is not None
        assert "elicitations" in error.error.data
        elicit_data = error.error.data["elicitations"][0]
        assert elicit_data["mode"] == "url"
        assert elicit_data["message"] == "Please authenticate"
        assert elicit_data["url"] == "https://example.com/oauth"
        assert elicit_data["elicitationId"] == "oauth-flow-1"

    def test_inherits_from_mcp_error(self) -> None:
        """Test that UrlElicitationRequiredError inherits from McpError."""
        elicitation = ElicitRequestURLParams(
            mode="url",
            message="Auth required",
            url="https://example.com/auth",
            elicitationId="test-123",
        )
        error = UrlElicitationRequiredError([elicitation])

        assert isinstance(error, McpError)
        assert isinstance(error, Exception)

    def test_exception_message(self) -> None:
        """Test that exception message is set correctly."""
        elicitation = ElicitRequestURLParams(
            mode="url",
            message="Auth required",
            url="https://example.com/auth",
            elicitationId="test-123",
        )
        error = UrlElicitationRequiredError([elicitation])

        # The exception's string representation should match the message
        assert str(error) == "URL elicitation required"
