"""Tests for MCP exception classes."""

import pickle

import pytest

from mcp.shared.exceptions import MCPError, UrlElicitationRequiredError
from mcp.types import URL_ELICITATION_REQUIRED, ElicitRequestURLParams, ErrorData


def test_url_elicitation_required_error_create_with_single_elicitation() -> None:
    """Test creating error with a single elicitation."""
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Auth required",
        url="https://example.com/auth",
        elicitation_id="test-123",
    )
    error = UrlElicitationRequiredError([elicitation])

    assert error.error.code == URL_ELICITATION_REQUIRED
    assert error.error.message == "URL elicitation required"
    assert len(error.elicitations) == 1
    assert error.elicitations[0].elicitation_id == "test-123"


def test_url_elicitation_required_error_create_with_multiple_elicitations() -> None:
    """Test creating error with multiple elicitations uses plural message."""
    elicitations = [
        ElicitRequestURLParams(
            mode="url",
            message="Auth 1",
            url="https://example.com/auth1",
            elicitation_id="test-1",
        ),
        ElicitRequestURLParams(
            mode="url",
            message="Auth 2",
            url="https://example.com/auth2",
            elicitation_id="test-2",
        ),
    ]
    error = UrlElicitationRequiredError(elicitations)

    assert error.error.message == "URL elicitations required"  # Plural
    assert len(error.elicitations) == 2


def test_url_elicitation_required_error_custom_message() -> None:
    """Test creating error with a custom message."""
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Auth required",
        url="https://example.com/auth",
        elicitation_id="test-123",
    )
    error = UrlElicitationRequiredError([elicitation], message="Custom message")

    assert error.error.message == "Custom message"


def test_url_elicitation_required_error_from_error_data() -> None:
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
    assert error.elicitations[0].elicitation_id == "test-123"
    assert error.elicitations[0].url == "https://example.com/auth"


def test_url_elicitation_required_error_from_error_data_wrong_code() -> None:
    """Test that from_error raises ValueError for wrong error code."""
    error_data = ErrorData(
        code=-32600,  # Wrong code
        message="Some other error",
        data={},
    )

    with pytest.raises(ValueError, match="Expected error code"):
        UrlElicitationRequiredError.from_error(error_data)


def test_url_elicitation_required_error_serialization_roundtrip() -> None:
    """Test that error can be serialized and reconstructed."""
    original = UrlElicitationRequiredError(
        [
            ElicitRequestURLParams(
                mode="url",
                message="Auth required",
                url="https://example.com/auth",
                elicitation_id="test-123",
            )
        ]
    )

    # Simulate serialization over wire
    error_data = original.error

    # Reconstruct
    reconstructed = UrlElicitationRequiredError.from_error(error_data)

    assert reconstructed.elicitations[0].elicitation_id == original.elicitations[0].elicitation_id
    assert reconstructed.elicitations[0].url == original.elicitations[0].url
    assert reconstructed.elicitations[0].message == original.elicitations[0].message


def test_url_elicitation_required_error_data_contains_elicitations() -> None:
    """Test that error data contains properly serialized elicitations."""
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Please authenticate",
        url="https://example.com/oauth",
        elicitation_id="oauth-flow-1",
    )
    error = UrlElicitationRequiredError([elicitation])

    assert error.error.data is not None
    assert "elicitations" in error.error.data
    elicit_data = error.error.data["elicitations"][0]
    assert elicit_data["mode"] == "url"
    assert elicit_data["message"] == "Please authenticate"
    assert elicit_data["url"] == "https://example.com/oauth"
    assert elicit_data["elicitationId"] == "oauth-flow-1"


def test_url_elicitation_required_error_inherits_from_mcp_error() -> None:
    """Test that UrlElicitationRequiredError inherits from MCPError."""
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Auth required",
        url="https://example.com/auth",
        elicitation_id="test-123",
    )
    error = UrlElicitationRequiredError([elicitation])

    assert isinstance(error, MCPError)
    assert isinstance(error, Exception)


def test_url_elicitation_required_error_exception_message() -> None:
    """Test that exception message is set correctly."""
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Auth required",
        url="https://example.com/auth",
        elicitation_id="test-123",
    )
    error = UrlElicitationRequiredError([elicitation])

    # The exception's string representation should match the message
    assert str(error) == "URL elicitation required"


def test_mcp_error_pickle_roundtrip() -> None:
    """Test that MCPError survives a pickle round-trip."""
    original = MCPError(code=-32600, message="Invalid request", data={"detail": "bad"})

    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is MCPError
    assert restored.error.code == original.error.code
    assert restored.error.message == original.error.message
    assert restored.error.data == original.error.data


def test_url_elicitation_required_error_pickle_roundtrip() -> None:
    """Test that UrlElicitationRequiredError survives a pickle round-trip."""
    elicitations = [
        ElicitRequestURLParams(
            mode="url",
            message="Auth required",
            url="https://example.com/auth",
            elicitation_id="test-123",
        ),
    ]
    original = UrlElicitationRequiredError(elicitations, message="Please authenticate")

    restored = pickle.loads(pickle.dumps(original))

    assert type(restored) is UrlElicitationRequiredError
    assert restored.error.code == URL_ELICITATION_REQUIRED
    assert restored.error.message == "Please authenticate"
    assert len(restored.elicitations) == 1
    assert restored.elicitations[0].elicitation_id == "test-123"
    assert restored.elicitations[0].url == "https://example.com/auth"


def test_url_elicitation_required_error_pickle_default_message() -> None:
    """Test pickle round-trip preserves the auto-generated default message."""
    elicitations = [
        ElicitRequestURLParams(
            mode="url",
            message="Auth",
            url="https://example.com/auth",
            elicitation_id="e1",
        ),
        ElicitRequestURLParams(
            mode="url",
            message="Auth2",
            url="https://example.com/auth2",
            elicitation_id="e2",
        ),
    ]
    original = UrlElicitationRequiredError(elicitations)

    restored = pickle.loads(pickle.dumps(original))

    assert restored.error.message == "URL elicitations required"
    assert len(restored.elicitations) == 2
