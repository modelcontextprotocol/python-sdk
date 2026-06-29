import pytest
from mcp_types import URL_ELICITATION_REQUIRED, ElicitRequestURLParams, ErrorData, JSONRPCError

from mcp.shared.exceptions import MCPError, UrlElicitationRequiredError


def test_url_elicitation_required_error_create_with_single_elicitation() -> None:
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
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Auth required",
        url="https://example.com/auth",
        elicitation_id="test-123",
    )
    error = UrlElicitationRequiredError([elicitation], message="Custom message")

    assert error.error.message == "Custom message"


def test_url_elicitation_required_error_from_error_data() -> None:
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
    error_data = ErrorData(
        code=-32600,  # Wrong code
        message="Some other error",
        data={},
    )

    with pytest.raises(ValueError, match="Expected error code"):
        UrlElicitationRequiredError.from_error(error_data)


def test_url_elicitation_required_error_serialization_roundtrip() -> None:
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

    # `.error` stands in for the wire payload; no JSON encode/decode needed
    error_data = original.error

    reconstructed = UrlElicitationRequiredError.from_error(error_data)

    assert reconstructed.elicitations[0].elicitation_id == original.elicitations[0].elicitation_id
    assert reconstructed.elicitations[0].url == original.elicitations[0].url
    assert reconstructed.elicitations[0].message == original.elicitations[0].message


def test_url_elicitation_required_error_data_contains_elicitations() -> None:
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
    elicitation = ElicitRequestURLParams(
        mode="url",
        message="Auth required",
        url="https://example.com/auth",
        elicitation_id="test-123",
    )
    error = UrlElicitationRequiredError([elicitation])

    assert str(error) == "URL elicitation required"


def test_from_jsonrpc_error_preserves_code_message_and_data() -> None:
    wire = JSONRPCError(
        jsonrpc="2.0",
        id=3,
        error=ErrorData(code=URL_ELICITATION_REQUIRED, message="go elsewhere", data={"hint": "y"}),
    )
    error = MCPError.from_jsonrpc_error(wire)
    assert error.error == ErrorData(code=URL_ELICITATION_REQUIRED, message="go elsewhere", data={"hint": "y"})
