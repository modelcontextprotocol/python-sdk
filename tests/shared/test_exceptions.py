"""Tests for MCP exception classes."""

from builtins import BaseExceptionGroup

import anyio
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


# Tests for unwrap_task_group_exception


@pytest.mark.anyio
async def test_unwrap_single_error() -> None:
    """Test that a single exception is returned as-is."""
    from mcp.shared.exceptions import unwrap_task_group_exception

    error = ValueError("test error")
    result = unwrap_task_group_exception(error)
    assert result is error


@pytest.mark.anyio
async def test_unwrap_exception_group_with_real_error() -> None:
    """Test that real error is extracted from ExceptionGroup."""
    from mcp.shared.exceptions import unwrap_task_group_exception

    real_error = ConnectionError("connection failed")

    # Simulate what anyio does: create exception group with real error + cancelled
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: (_ for _ in ()).throw(real_error))
            tg.start_soon(anyio.sleep, 999)  # Will be cancelled
    except BaseExceptionGroup as e:
        result = unwrap_task_group_exception(e)
        assert isinstance(result, ConnectionError)
        assert str(result) == "connection failed"


@pytest.mark.anyio
async def test_unwrap_exception_group_all_cancelled() -> None:
    """Test that when all exceptions are cancelled, the group is re-raised."""
    from mcp.shared.exceptions import unwrap_task_group_exception

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(anyio.sleep, 999)
            tg.cancel_scope.cancel()
    except BaseExceptionGroup as e:
        # Should return the group if all are cancelled
        result = unwrap_task_group_exception(e)
        assert isinstance(result, BaseExceptionGroup)


@pytest.mark.anyio
async def test_unwrap_preserves_non_cancelled_errors() -> None:
    """Test that all non-cancelled exceptions are preserved."""
    from mcp.shared.exceptions import unwrap_task_group_exception

    error1 = ValueError("error 1")
    error2 = RuntimeError("error 2")

    # Create an exception group with multiple real errors
    group = BaseExceptionGroup("multiple", [error1, error2])

    result = unwrap_task_group_exception(group)
    # Should return the first non-cancelled error
    assert result is error1
