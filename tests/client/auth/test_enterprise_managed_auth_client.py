"""Tests for Enterprise Managed Authorization client-side implementation."""

import time
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
import pytest
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth import OAuthTokenError
from mcp.client.auth.extensions.enterprise_managed_auth import (
    EnterpriseAuthOAuthClientProvider,
    IDJAGClaims,
    TokenExchangeParameters,
    TokenExchangeResponse,
    decode_id_jag,
    validate_token_exchange_params,
)
from mcp.shared.auth import OAuthClientMetadata

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_id_token() -> str:
    """Generate a sample ID token for testing."""
    payload = {
        "iss": "https://idp.example.com",
        "sub": "user123",
        "aud": "mcp-client-app",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "email": "user@example.com",
    }
    return jwt.encode(payload, "secret", algorithm="HS256")


@pytest.fixture
def sample_id_jag() -> str:
    """Generate a sample ID-JAG token for testing."""
    payload = {
        "jti": "unique-jwt-id-12345",
        "iss": "https://idp.example.com",
        "sub": "user123",
        "aud": "https://auth.mcp-server.example/",
        "resource": "https://mcp-server.example/",
        "client_id": "mcp-client-app",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "scope": "read write",
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    # Manually add typ to header
    header = jwt.get_unverified_header(token)
    header["typ"] = "oauth-id-jag+jwt"

    return jwt.encode(payload, "secret", algorithm="HS256", headers={"typ": "oauth-id-jag+jwt"})


@pytest.fixture
def mock_token_storage() -> Any:
    """Create a mock token storage."""
    storage = Mock()
    storage.get_tokens = AsyncMock(return_value=None)
    storage.set_tokens = AsyncMock()
    storage.get_client_info = AsyncMock(return_value=None)
    storage.set_client_info = AsyncMock()
    return storage


# ============================================================================
# Tests for TokenExchangeParameters
# ============================================================================


def test_token_exchange_params_from_id_token():
    """Test creating TokenExchangeParameters from ID token."""
    params = TokenExchangeParameters.from_id_token(
        id_token="eyJhbGc...",
        mcp_server_auth_issuer="https://auth.server.example/",
        mcp_server_resource_id="https://server.example/",
        scope="read write",
    )

    assert params.subject_token == "eyJhbGc..."
    assert params.subject_token_type == "urn:ietf:params:oauth:token-type:id_token"
    assert params.audience == "https://auth.server.example/"
    assert params.resource == "https://server.example/"
    assert params.scope == "read write"
    assert params.requested_token_type == "urn:ietf:params:oauth:token-type:id-jag"


def test_token_exchange_params_from_saml_assertion():
    """Test creating TokenExchangeParameters from SAML assertion."""
    params = TokenExchangeParameters.from_saml_assertion(
        saml_assertion="<saml:Assertion>...</saml:Assertion>",
        mcp_server_auth_issuer="https://auth.server.example/",
        mcp_server_resource_id="https://server.example/",
        scope="read",
    )

    assert params.subject_token == "<saml:Assertion>...</saml:Assertion>"
    assert params.subject_token_type == "urn:ietf:params:oauth:token-type:saml2"
    assert params.audience == "https://auth.server.example/"
    assert params.resource == "https://server.example/"
    assert params.scope == "read"


def test_validate_token_exchange_params_valid():
    """Test validating valid token exchange parameters."""
    params = TokenExchangeParameters.from_id_token(
        id_token="token",
        mcp_server_auth_issuer="https://auth.example/",
        mcp_server_resource_id="https://server.example/",
    )

    # Should not raise
    validate_token_exchange_params(params)


def test_validate_token_exchange_params_invalid_token_type():
    """Test validation fails for invalid subject token type."""
    params = TokenExchangeParameters(
        subject_token="token",
        subject_token_type="invalid:type",
        audience="https://auth.example/",
        resource="https://server.example/",
    )

    with pytest.raises(ValueError, match="Invalid subject_token_type"):
        validate_token_exchange_params(params)


def test_validate_token_exchange_params_missing_subject_token():
    """Test validation fails for missing subject token."""
    params = TokenExchangeParameters(
        subject_token="",
        subject_token_type="urn:ietf:params:oauth:token-type:id_token",
        audience="https://auth.example/",
        resource="https://server.example/",
    )

    with pytest.raises(ValueError, match="subject_token is required"):
        validate_token_exchange_params(params)


# ============================================================================
# Tests for TokenExchangeResponse
# ============================================================================


def test_token_exchange_response_parsing():
    """Test parsing token exchange response."""
    response_json = """{
        "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
        "access_token": "eyJhbGc...",
        "token_type": "N_A",
        "scope": "read write",
        "expires_in": 300
    }"""

    response = TokenExchangeResponse.model_validate_json(response_json)

    assert response.issued_token_type == "urn:ietf:params:oauth:token-type:id-jag"
    assert response.id_jag == "eyJhbGc..."
    assert response.access_token == "eyJhbGc..."
    assert response.token_type == "N_A"
    assert response.scope == "read write"
    assert response.expires_in == 300


def test_token_exchange_response_id_jag_property():
    """Test id_jag property returns access_token."""
    response = TokenExchangeResponse(
        issued_token_type="urn:ietf:params:oauth:token-type:id-jag",
        access_token="the-id-jag-token",
        token_type="N_A",
    )

    assert response.id_jag == "the-id-jag-token"


# ============================================================================
# Tests for IDJAGClaims
# ============================================================================


def test_decode_id_jag(sample_id_jag: str):
    """Test decoding ID-JAG token."""
    claims = decode_id_jag(sample_id_jag)

    assert claims.iss == "https://idp.example.com"
    assert claims.sub == "user123"
    assert claims.aud == "https://auth.mcp-server.example/"
    assert claims.resource == "https://mcp-server.example/"
    assert claims.client_id == "mcp-client-app"
    assert claims.scope == "read write"


def test_id_jag_claims_with_extra_fields():
    """Test IDJAGClaims allows extra fields."""
    claims_data = {
        "typ": "oauth-id-jag+jwt",
        "jti": "jti123",
        "iss": "https://idp.example.com",
        "sub": "user123",
        "aud": "https://auth.server.example/",
        "resource": "https://server.example/",
        "client_id": "client123",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "scope": "read",
        "email": "user@example.com",
        "custom_claim": "custom_value",  # Extra field
    }

    claims = IDJAGClaims.model_validate(claims_data)
    assert claims.email == "user@example.com"
    # Extra field should be preserved
    assert claims.model_extra is not None and claims.model_extra.get("custom_claim") == "custom_value"


# ============================================================================
# Tests for EnterpriseAuthOAuthClientProvider
# ============================================================================


@pytest.mark.anyio
async def test_exchange_token_for_id_jag_success(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test successful token exchange for ID-JAG."""
    # Create provider
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
        scope="read write",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
            client_name="Test Client",
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            "scope": "read write",
            "expires_in": 300,
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    id_jag = await provider.exchange_token_for_id_jag(mock_client)

    # Verify
    assert id_jag == sample_id_jag
    assert provider._id_jag == sample_id_jag

    # Verify request was made correctly
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://idp.example.com/oauth2/token"
    assert call_args[1]["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert call_args[1]["data"]["requested_token_type"] == "urn:ietf:params:oauth:token-type:id-jag"
    assert call_args[1]["data"]["audience"] == "https://auth.mcp-server.example/"
    assert call_args[1]["data"]["resource"] == "https://mcp-server.example/"


@pytest.mark.anyio
async def test_exchange_token_for_id_jag_error(sample_id_token: str, mock_token_storage: Any):
    """Test token exchange failure handling."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Mock error response
    mock_response = httpx.Response(
        status_code=400,
        json={
            "error": "invalid_request",
            "error_description": "Invalid subject token",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should raise OAuthTokenError
    with pytest.raises(OAuthTokenError, match="Token exchange failed"):
        await provider.exchange_token_for_id_jag(mock_client)


@pytest.mark.anyio
async def test_exchange_token_for_id_jag_unexpected_token_type(sample_id_token: str, mock_token_storage: Any):
    """Test token exchange with unexpected token type."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Mock response with wrong token type
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "access_token": "some-token",
            "token_type": "Bearer",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should raise OAuthTokenError
    with pytest.raises(OAuthTokenError, match="Unexpected token type"):
        await provider.exchange_token_for_id_jag(mock_client)


@pytest.mark.anyio
async def test_exchange_id_jag_for_access_token_success(sample_id_jag: str, mock_token_storage: Any):
    """Test successful JWT bearer grant to get access token."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set up OAuth metadata
    from mcp.shared.auth import OAuthMetadata

    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "token_type": "Bearer",
            "access_token": "mcp-access-token-12345",
            "expires_in": 3600,
            "scope": "read write",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform JWT bearer grant
    token = await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)

    # Verify
    assert token.access_token == "mcp-access-token-12345"
    assert token.token_type == "Bearer"
    assert token.expires_in == 3600

    # Verify tokens were stored
    mock_token_storage.set_tokens.assert_called_once()

    # Verify request was made correctly
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[1]["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert call_args[1]["data"]["assertion"] == sample_id_jag


@pytest.mark.anyio
async def test_exchange_id_jag_for_access_token_no_metadata(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant fails without OAuth metadata."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # No OAuth metadata set
    mock_client = Mock(spec=httpx.AsyncClient)

    # Should raise OAuthFlowError
    from mcp.client.auth import OAuthFlowError

    with pytest.raises(OAuthFlowError, match="token endpoint not discovered"):
        await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)


@pytest.mark.anyio
async def test_perform_authorization_not_implemented(mock_token_storage: Any):
    """Test that _perform_authorization raises NotImplementedError."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Should raise NotImplementedError
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        await provider._perform_authorization()


@pytest.mark.anyio
async def test_perform_authorization_with_valid_tokens(mock_token_storage: Any):
    """Test that _perform_authorization returns dummy request when tokens are valid."""
    from mcp.shared.auth import OAuthToken

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set valid tokens
    provider.context.current_tokens = OAuthToken(
        token_type="Bearer",
        access_token="valid-token",
        expires_in=3600,
    )
    provider.context.token_expiry_time = time.time() + 3600

    # Should return a dummy request
    request = await provider._perform_authorization()
    assert request.method == "GET"
    assert str(request.url) == "https://mcp-server.example/"


@pytest.mark.anyio
async def test_exchange_token_with_client_authentication(
    sample_id_token: str, sample_id_jag: str, mock_token_storage: Any
):
    """Test token exchange with client authentication."""
    from mcp.shared.auth import OAuthClientInformationFull

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
        scope="read write",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
            client_name="Test Client",
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set client info with secret
    provider.context.client_info = OAuthClientInformationFull(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            "scope": "read write",
            "expires_in": 300,
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    id_jag = await provider.exchange_token_for_id_jag(mock_client)

    # Verify the ID-JAG was returned
    assert id_jag == sample_id_jag

    # Verify client credentials were included
    call_args = mock_client.post.call_args
    assert call_args[1]["data"]["client_id"] == "test-client-id"
    assert call_args[1]["data"]["client_secret"] == "test-client-secret"


@pytest.mark.anyio
async def test_exchange_token_with_client_id_only(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test token exchange with client_id but no client_secret (covers branch 232->235)."""
    from mcp.shared.auth import OAuthClientInformationFull

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
        scope="read write",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
            client_name="Test Client",
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set client info WITHOUT secret (client_secret=None)
    provider.context.client_info = OAuthClientInformationFull(
        client_id="test-client-id",
        client_secret=None,  # No secret
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            "scope": "read write",
            "expires_in": 300,
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    id_jag = await provider.exchange_token_for_id_jag(mock_client)

    # Verify the ID-JAG was returned
    assert id_jag == sample_id_jag

    # Verify client_id was included but NOT client_secret
    call_args = mock_client.post.call_args
    assert call_args[1]["data"]["client_id"] == "test-client-id"
    assert "client_secret" not in call_args[1]["data"]


@pytest.mark.anyio
async def test_exchange_token_http_error(sample_id_token: str, mock_token_storage: Any):
    """Test token exchange with HTTP error."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))

    # Should raise OAuthTokenError
    with pytest.raises(OAuthTokenError, match="HTTP error during token exchange"):
        await provider.exchange_token_for_id_jag(mock_client)


@pytest.mark.anyio
async def test_exchange_token_non_json_error_response(sample_id_token: str, mock_token_storage: Any):
    """Test token exchange with non-JSON error response."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Mock error response with non-JSON content
    mock_response = httpx.Response(
        status_code=500,
        content=b"Internal Server Error",
        headers={"content-type": "text/plain"},
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should raise OAuthTokenError with default error
    with pytest.raises(OAuthTokenError, match="Token exchange failed: unknown_error"):
        await provider.exchange_token_for_id_jag(mock_client)


@pytest.mark.anyio
async def test_exchange_token_warning_for_non_na_token_type(
    sample_id_token: str, sample_id_jag: str, mock_token_storage: Any
):
    """Test token exchange logs warning for non-N_A token type."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Mock response with different token_type
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "Bearer",  # Not N_A
            "scope": "read write",
            "expires_in": 300,
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should succeed but log warning
    import logging

    with patch.object(
        logging.getLogger("mcp.client.auth.extensions.enterprise_managed_auth"), "warning"
    ) as mock_warning:
        id_jag = await provider.exchange_token_for_id_jag(mock_client)
        assert id_jag == sample_id_jag
        mock_warning.assert_called_once()


@pytest.mark.anyio
async def test_exchange_id_jag_with_client_authentication(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant with client authentication."""
    from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set client info with secret
    provider.context.client_info = OAuthClientInformationFull(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "token_type": "Bearer",
            "access_token": "mcp-access-token-12345",
            "expires_in": 3600,
            "scope": "read write",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform JWT bearer grant
    token = await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)

    # Verify token was returned
    assert token.access_token == "mcp-access-token-12345"

    # Verify client credentials were included
    call_args = mock_client.post.call_args
    assert call_args[1]["data"]["client_id"] == "test-client-id"
    assert call_args[1]["data"]["client_secret"] == "test-client-secret"


@pytest.mark.anyio
async def test_exchange_id_jag_with_client_id_only(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant with client_id but no client_secret (covers branch 304->307)."""
    from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set client info WITHOUT secret (client_secret=None)
    provider.context.client_info = OAuthClientInformationFull(
        client_id="test-client-id",
        client_secret=None,  # No secret
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "token_type": "Bearer",
            "access_token": "mcp-access-token-12345",
            "expires_in": 3600,
            "scope": "read write",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform JWT bearer grant
    token = await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)

    # Verify token was returned correctly
    assert token.access_token == "mcp-access-token-12345"
    assert token.token_type == "Bearer"

    # Verify client_id was included but NOT client_secret
    call_args = mock_client.post.call_args
    assert call_args[1]["data"]["client_id"] == "test-client-id"
    assert "client_secret" not in call_args[1]["data"]


@pytest.mark.anyio
async def test_exchange_id_jag_error_response(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant with error response."""
    from mcp.shared.auth import OAuthMetadata

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Mock error response
    mock_response = httpx.Response(
        status_code=400,
        json={
            "error": "invalid_grant",
            "error_description": "Invalid assertion",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should raise OAuthTokenError
    with pytest.raises(OAuthTokenError, match="JWT bearer grant failed"):
        await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)


@pytest.mark.anyio
async def test_exchange_id_jag_non_json_error(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant with non-JSON error response."""
    from mcp.shared.auth import OAuthMetadata

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Mock error response with non-JSON content
    mock_response = httpx.Response(
        status_code=503,
        content=b"Service Unavailable",
        headers={"content-type": "text/html"},
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should raise OAuthTokenError with default error
    with pytest.raises(OAuthTokenError, match="JWT bearer grant failed: unknown_error"):
        await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)


@pytest.mark.anyio
async def test_exchange_id_jag_http_error(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant with HTTP error."""
    from mcp.shared.auth import OAuthMetadata

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("Request timeout"))

    # Should raise OAuthTokenError
    with pytest.raises(OAuthTokenError, match="HTTP error during JWT bearer grant"):
        await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)


@pytest.mark.anyio
async def test_exchange_token_with_client_info_but_no_client_id(
    sample_id_token: str, sample_id_jag: str, mock_token_storage: Any
):
    """Test token exchange when client_info exists but client_id is None (covers line 231)."""
    from mcp.shared.auth import OAuthClientInformationFull

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
        scope="read write",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
            client_name="Test Client",
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set client info with client_id=None
    provider.context.client_info = OAuthClientInformationFull(
        client_id=None,  # This should skip the client_id assignment
        client_secret="test-secret",
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            "scope": "read write",
            "expires_in": 300,
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    id_jag = await provider.exchange_token_for_id_jag(mock_client)

    # Verify the ID-JAG was returned
    assert id_jag == sample_id_jag

    # Verify client_id was not included (None), but client_secret was included
    call_args = mock_client.post.call_args
    assert "client_id" not in call_args[1]["data"]
    assert call_args[1]["data"]["client_secret"] == "test-secret"


@pytest.mark.anyio
async def test_exchange_id_jag_with_client_info_but_no_client_id(sample_id_jag: str, mock_token_storage: Any):
    """Test ID-JAG exchange when client_info exists but client_id is None (covers line 302)."""
    from pydantic import AnyHttpUrl

    from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Set client info with client_id=None
    provider.context.client_info = OAuthClientInformationFull(
        client_id=None,  # This should skip the client_id assignment
        client_secret="test-secret",
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "token_type": "Bearer",
            "access_token": "mcp-access-token-12345",
            "expires_in": 3600,
            "scope": "read write",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform JWT bearer grant
    token = await provider.exchange_id_jag_for_access_token(mock_client, sample_id_jag)

    # Verify
    assert token.access_token == "mcp-access-token-12345"
    assert token.token_type == "Bearer"
    assert token.expires_in == 3600

    # Verify client_id was not included (None), but client_secret was included
    call_args = mock_client.post.call_args
    assert "client_id" not in call_args[1]["data"]
    assert call_args[1]["data"]["client_secret"] == "test-secret"


def test_validate_token_exchange_params_missing_audience():
    """Test validation fails for missing audience."""
    params = TokenExchangeParameters(
        subject_token="token",
        subject_token_type="urn:ietf:params:oauth:token-type:id_token",
        audience="",
        resource="https://server.example/",
    )

    with pytest.raises(ValueError, match="audience is required"):
        validate_token_exchange_params(params)


def test_validate_token_exchange_params_missing_resource():
    """Test validation fails for missing resource."""
    params = TokenExchangeParameters(
        subject_token="token",
        subject_token_type="urn:ietf:params:oauth:token-type:id_token",
        audience="https://auth.example/",
        resource="",
    )

    with pytest.raises(ValueError, match="resource is required"):
        validate_token_exchange_params(params)
