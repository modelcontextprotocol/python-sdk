"""Tests for Enterprise Managed Authorization client-side implementation."""

import time
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest

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
def sample_id_token():
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
def sample_id_jag():
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
def mock_token_storage():
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


def test_decode_id_jag(sample_id_jag):
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
    assert claims.model_extra.get("custom_claim") == "custom_value"


# ============================================================================
# Tests for EnterpriseAuthOAuthClientProvider
# ============================================================================


@pytest.mark.anyio
async def test_exchange_token_for_id_jag_success(sample_id_token, sample_id_jag, mock_token_storage):
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
            redirect_uris=["http://localhost:8080/callback"],
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
async def test_exchange_token_for_id_jag_error(sample_id_token, mock_token_storage):
    """Test token exchange failure handling."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"],
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
async def test_exchange_token_for_id_jag_unexpected_token_type(sample_id_token, mock_token_storage):
    """Test token exchange with unexpected token type."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"],
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
async def test_exchange_id_jag_for_access_token_success(sample_id_jag, mock_token_storage):
    """Test successful JWT bearer grant to get access token."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set up OAuth metadata
    from mcp.shared.auth import OAuthMetadata
    from pydantic import HttpUrl

    provider.context.oauth_metadata = OAuthMetadata(
        issuer=HttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=HttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=HttpUrl("https://auth.mcp-server.example/oauth2/token"),
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
async def test_exchange_id_jag_for_access_token_no_metadata(sample_id_jag, mock_token_storage):
    """Test JWT bearer grant fails without OAuth metadata."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"],
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
async def test_perform_authorization_not_implemented(mock_token_storage):
    """Test that _perform_authorization raises NotImplementedError."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token="dummy-token",
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Should raise NotImplementedError
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        await provider._perform_authorization()

