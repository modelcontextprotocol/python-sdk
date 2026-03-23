"""Tests for Enterprise Managed Authorization client-side implementation."""

import logging
import time
import urllib.parse
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
import pytest
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth import OAuthFlowError, OAuthTokenError
from mcp.client.auth.extensions.enterprise_managed_auth import (
    EnterpriseAuthOAuthClientProvider,
    IDJAGClaims,
    IDJAGTokenExchangeResponse,
    TokenExchangeParameters,
    decode_id_jag,
    validate_token_exchange_params,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata, OAuthToken


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
    # Create typed claims using IDJAGClaims model
    claims = IDJAGClaims(
        typ="oauth-id-jag+jwt",
        jti="unique-jwt-id-12345",
        iss="https://idp.example.com",
        sub="user123",
        aud="https://auth.mcp-server.example/",
        resource="https://mcp-server.example/",
        client_id="mcp-client-app",
        exp=int(time.time()) + 300,
        iat=int(time.time()),
        scope="read write",
        email=None,  # Optional field
    )

    # Dump to dict for JWT encoding (exclude typ as it goes in header)
    payload = claims.model_dump(exclude={"typ"}, exclude_none=True)

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

    with pytest.raises(OAuthFlowError, match="Invalid subject_token_type"):
        validate_token_exchange_params(params)


def test_validate_token_exchange_params_missing_subject_token():
    """Test validation fails for missing subject token."""
    params = TokenExchangeParameters(
        subject_token="",
        subject_token_type="urn:ietf:params:oauth:token-type:id_token",
        audience="https://auth.example/",
        resource="https://server.example/",
    )

    with pytest.raises(OAuthFlowError, match="subject_token is required"):
        validate_token_exchange_params(params)


def test_token_exchange_response_parsing():
    """Test parsing token exchange response."""
    response_json = """{
        "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
        "access_token": "eyJhbGc...",
        "token_type": "N_A",
        "scope": "read write",
        "expires_in": 300
    }"""

    response = IDJAGTokenExchangeResponse.model_validate_json(response_json)

    assert response.issued_token_type == "urn:ietf:params:oauth:token-type:id-jag"
    assert response.id_jag == "eyJhbGc..."
    assert response.access_token == "eyJhbGc..."
    assert response.token_type == "N_A"
    assert response.scope == "read write"
    assert response.expires_in == 300


def test_token_exchange_response_id_jag_property():
    """Test id_jag property returns access_token."""
    response = IDJAGTokenExchangeResponse(
        issued_token_type="urn:ietf:params:oauth:token-type:id-jag",
        access_token="the-id-jag-token",
        token_type="N_A",
    )

    assert response.id_jag == "the-id-jag-token"


def test_decode_id_jag(sample_id_jag: str):
    """Test decoding ID-JAG token."""
    claims = decode_id_jag(sample_id_jag)

    assert claims.iss == "https://idp.example.com"
    assert claims.sub == "user123"
    assert claims.aud == "https://auth.mcp-server.example/"
    assert claims.resource == "https://mcp-server.example/"
    assert claims.client_id == "mcp-client-app"
    assert claims.scope == "read write"


def test_decode_id_jag_invalid_jwt():
    """Test decoding malformed ID-JAG raises appropriate error."""
    with pytest.raises(jwt.DecodeError):
        decode_id_jag("not.a.valid.jwt")


def test_decode_id_jag_incomplete_jwt():
    """Test decoding incomplete JWT raises error."""
    with pytest.raises(jwt.DecodeError):
        decode_id_jag("only.two.parts")


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
    """Test building JWT bearer grant request."""
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

    # Build JWT bearer grant request
    request = await provider.exchange_id_jag_for_access_token(sample_id_jag)

    # Verify the request was built correctly
    assert isinstance(request, httpx.Request)
    assert request.method == "POST"
    assert str(request.url) == "https://auth.mcp-server.example/oauth2/token"

    # Parse the request body
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert body_params["grant_type"][0] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert body_params["assertion"][0] == sample_id_jag


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

    # Should raise OAuthFlowError
    with pytest.raises(OAuthFlowError, match="token endpoint not discovered"):
        await provider.exchange_id_jag_for_access_token(sample_id_jag)


@pytest.mark.anyio
async def test_perform_authorization_full_flow(mock_token_storage: Any, sample_id_jag: str):
    """Test that _perform_authorization performs token exchange and builds JWT bearer request."""
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

    # Mock the IDP token exchange response
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = httpx.Response(
            status_code=200,
            json={
                "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
                "access_token": sample_id_jag,
                "token_type": "N_A",
            },
        )
        mock_client.post = AsyncMock(return_value=mock_response)

        # Perform authorization
        request = await provider._perform_authorization()

        # Verify it returns an httpx.Request for JWT bearer grant
        assert isinstance(request, httpx.Request)
        assert request.method == "POST"
        assert str(request.url) == "https://auth.mcp-server.example/oauth2/token"

        # Verify the request contains JWT bearer grant
        body_params = urllib.parse.parse_qs(request.content.decode())
        assert body_params["grant_type"][0] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
        assert body_params["assertion"][0] == sample_id_jag


@pytest.mark.anyio
async def test_perform_authorization_with_valid_tokens(mock_token_storage: Any, sample_id_jag: str):
    """Test that _perform_authorization uses cached ID-JAG when tokens are valid."""
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

    # Set valid tokens and cached ID-JAG with valid expiry
    provider.context.current_tokens = OAuthToken(
        token_type="Bearer",
        access_token="valid-token",
        expires_in=3600,
    )
    provider.context.token_expiry_time = time.time() + 3600
    provider._id_jag = sample_id_jag
    provider._id_jag_expiry = time.time() + 300  # Valid for 5 more minutes

    # Should return a JWT bearer grant request using cached ID-JAG
    request = await provider._perform_authorization()
    assert isinstance(request, httpx.Request)
    assert request.method == "POST"
    assert str(request.url) == "https://auth.mcp-server.example/oauth2/token"

    # Verify it uses the cached ID-JAG
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert body_params["assertion"][0] == sample_id_jag


@pytest.mark.anyio
async def test_exchange_token_with_client_authentication(
    sample_id_token: str, sample_id_jag: str, mock_token_storage: Any
):
    """Test token exchange with client authentication."""
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
        idp_client_id="test-idp-client-id",  # IdP client ID, not MCP client ID
        idp_client_secret="test-idp-client-secret",  # IdP client secret
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
    assert call_args[1]["data"]["client_id"] == "test-idp-client-id"
    assert call_args[1]["data"]["client_secret"] == "test-idp-client-secret"


@pytest.mark.anyio
async def test_exchange_token_with_client_id_only(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test token exchange with client_id but no client_secret (covers branch 232->235)."""
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
        idp_client_id="test-idp-client-id",  # IdP client ID, not MCP client ID
        idp_client_secret=None,  # No secret
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
    assert call_args[1]["data"]["client_id"] == "test-idp-client-id"
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
async def test_exchange_token_malformed_json_error_response(sample_id_token: str, mock_token_storage: Any):
    """Test token exchange with malformed JSON error response that raises JSONDecodeError."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Mock error response with malformed JSON (will raise JSONDecodeError when parsing)
    mock_response = httpx.Response(
        status_code=400,
        content=b'{"error": "invalid_request", "invalid json structure',  # Malformed JSON
        headers={"content-type": "application/json"},
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should raise OAuthTokenError with default error message including status code
    with pytest.raises(OAuthTokenError, match=r"Token exchange failed.*HTTP 400"):
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
    with patch.object(
        logging.getLogger("mcp.client.auth.extensions.enterprise_managed_auth"), "warning"
    ) as mock_warning:
        id_jag = await provider.exchange_token_for_id_jag(mock_client)
        assert id_jag == sample_id_jag
        mock_warning.assert_called_once()


@pytest.mark.anyio
async def test_exchange_id_jag_with_client_authentication(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant request building with client authentication."""
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

    # Build JWT bearer grant request
    request = await provider.exchange_id_jag_for_access_token(sample_id_jag)

    # Verify request was built correctly
    assert isinstance(request, httpx.Request)
    assert request.method == "POST"

    # Verify client credentials were included in request body
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert body_params["client_id"][0] == "test-client-id"
    # With client_secret_basic (default), credentials should be in Authorization header
    assert "Authorization" in request.headers
    assert request.headers["Authorization"].startswith("Basic ")


@pytest.mark.anyio
async def test_exchange_id_jag_with_client_id_only(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant request building with client_id but no client_secret."""
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

    # Build JWT bearer grant request
    request = await provider.exchange_id_jag_for_access_token(sample_id_jag)

    # Verify request was built correctly
    assert isinstance(request, httpx.Request)

    # Verify client_id was included but NOT client_secret
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert body_params["client_id"][0] == "test-client-id"
    assert "client_secret" not in body_params
    # With no client_secret, there should be no Authorization header either
    assert "Authorization" not in request.headers or not request.headers["Authorization"].startswith("Basic ")


@pytest.mark.anyio
async def test_exchange_token_with_client_info_but_no_client_id(
    sample_id_token: str, sample_id_jag: str, mock_token_storage: Any
):
    """Test token exchange when only client_secret is provided (no client_id)."""
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
        idp_client_id=None,  # No client ID
        idp_client_secret="test-idp-secret",  # But has secret
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
    assert call_args[1]["data"]["client_secret"] == "test-idp-secret"


@pytest.mark.anyio
async def test_exchange_id_jag_with_client_info_but_no_client_id(sample_id_jag: str, mock_token_storage: Any):
    """Test ID-JAG exchange request building when client_info exists but client_id is None."""
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

    # Build JWT bearer grant request
    request = await provider.exchange_id_jag_for_access_token(sample_id_jag)

    # Verify request was built correctly
    assert isinstance(request, httpx.Request)

    # Verify client_id was not included (None), but client_secret should be handled
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert "client_id" not in body_params or body_params["client_id"][0] == ""


def test_validate_token_exchange_params_missing_audience():
    """Test validation fails for missing audience."""
    params = TokenExchangeParameters(
        subject_token="token",
        subject_token_type="urn:ietf:params:oauth:token-type:id_token",
        audience="",
        resource="https://server.example/",
    )

    with pytest.raises(OAuthFlowError, match="audience is required"):
        validate_token_exchange_params(params)


def test_validate_token_exchange_params_missing_resource():
    """Test validation fails for missing resource."""
    params = TokenExchangeParameters(
        subject_token="token",
        subject_token_type="urn:ietf:params:oauth:token-type:id_token",
        audience="https://auth.example/",
        resource="",
    )

    with pytest.raises(OAuthFlowError, match="resource is required"):
        validate_token_exchange_params(params)


@pytest.mark.anyio
async def test_exchange_id_jag_with_existing_auth_method(sample_id_jag: str, mock_token_storage: Any):
    """Test JWT bearer grant when token_endpoint_auth_method is already set (covers branch 323->326)."""
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

    # Set client info WITH auth method already set
    provider.context.client_info = OAuthClientInformationFull(
        client_id="test-client-id",
        client_secret="test-client-secret",
        token_endpoint_auth_method="client_secret_post",  # Already set
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
    )

    # Set up OAuth metadata
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Build JWT bearer grant request
    request = await provider.exchange_id_jag_for_access_token(sample_id_jag)

    # Verify request was built correctly
    assert isinstance(request, httpx.Request)

    # Verify it used client_secret_post (in body, not header)
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert body_params["client_id"][0] == "test-client-id"
    assert body_params["client_secret"][0] == "test-client-secret"
    # Should NOT have Authorization header for client_secret_post
    assert "Authorization" not in request.headers or not request.headers["Authorization"].startswith("Basic ")


@pytest.mark.anyio
async def test_perform_authorization_with_valid_tokens_no_id_jag(mock_token_storage: Any):
    """Test _perform_authorization when tokens are valid but no cached ID-JAG (covers branch 354->360)."""
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

    # Set valid tokens but NO cached ID-JAG
    provider.context.current_tokens = OAuthToken(
        token_type="Bearer",
        access_token="valid-token",
        expires_in=3600,
    )
    provider.context.token_expiry_time = time.time() + 3600
    provider._id_jag = None  # No cached ID-JAG

    # Mock the IDP token exchange response
    sample_id_jag = "test-id-jag-token"
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = httpx.Response(
            status_code=200,
            json={
                "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
                "access_token": sample_id_jag,
                "token_type": "N_A",
            },
        )
        mock_client.post = AsyncMock(return_value=mock_response)

        # Should fall through and perform full flow
        request = await provider._perform_authorization()

        # Verify it returns a JWT bearer grant request
        assert isinstance(request, httpx.Request)
        assert request.method == "POST"

        # Verify it made the IDP token exchange call
        mock_client.post.assert_called_once()


@pytest.mark.anyio
async def test_refresh_with_new_id_token(mock_token_storage: Any):
    """Test refresh_with_new_id_token helper method."""
    old_id_token = "old-id-token"
    new_id_token = "new-id-token"

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=old_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
    )

    provider = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example/",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
        ),
        storage=mock_token_storage,
        idp_token_endpoint="https://idp.example.com/oauth2/token",
        token_exchange_params=token_exchange_params,
    )

    # Set some existing tokens and cached ID-JAG
    provider.context.current_tokens = OAuthToken(
        token_type="Bearer",
        access_token="old-access-token",
        expires_in=3600,
    )
    provider._id_jag = "old-id-jag"
    provider._id_jag_expiry = time.time() + 3600

    # Verify initial state
    assert provider.token_exchange_params.subject_token == old_id_token
    assert provider._id_jag == "old-id-jag"
    assert provider._id_jag_expiry is not None
    assert provider.context.current_tokens.access_token == "old-access-token"

    # Call refresh with new ID token
    await provider.refresh_with_new_id_token(new_id_token)

    # Verify state after refresh
    assert provider.token_exchange_params.subject_token == new_id_token
    assert provider._id_jag is None  # Cached ID-JAG should be cleared
    assert provider._id_jag_expiry is None  # Expiry should be cleared
    assert provider.context.current_tokens is None  # Tokens should be cleared
    assert provider.context.token_expiry_time is None  # Expiry should be cleared


@pytest.mark.anyio
async def test_id_jag_expiry_tracking(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test that ID-JAG expiry is tracked when obtained from IdP."""
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

    # Mock HTTP response with expires_in
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            "expires_in": 300,  # 5 minutes
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    before_time = time.time()
    _ = await provider.exchange_token_for_id_jag(mock_client)
    after_time = time.time()

    # Verify ID-JAG was cached
    assert provider._id_jag == sample_id_jag
    # Verify expiry was set (should be current time + 300 seconds)
    assert provider._id_jag_expiry is not None
    assert before_time + 300 <= provider._id_jag_expiry <= after_time + 300


@pytest.mark.anyio
async def test_id_jag_expiry_default_when_not_provided(
    sample_id_token: str, sample_id_jag: str, mock_token_storage: Any
):
    """Test that default expiry (15 minutes = 900 seconds) is used when expires_in not provided."""
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

    # Mock HTTP response WITHOUT expires_in
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            # No expires_in field
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    before_time = time.time()
    await provider.exchange_token_for_id_jag(mock_client)
    after_time = time.time()

    # Verify default expiry was set (900 seconds = 15 minutes)
    assert provider._id_jag_expiry is not None
    assert before_time + 900 <= provider._id_jag_expiry <= after_time + 900


@pytest.mark.anyio
async def test_perform_authorization_checks_id_jag_expiry(mock_token_storage: Any, sample_id_jag: str):
    """Test that _perform_authorization checks ID-JAG expiry before reusing."""
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

    # Set valid tokens and cached ID-JAG that has EXPIRED
    provider.context.current_tokens = OAuthToken(
        token_type="Bearer",
        access_token="valid-token",
        expires_in=3600,
    )
    provider.context.token_expiry_time = time.time() + 3600
    provider._id_jag = sample_id_jag
    provider._id_jag_expiry = time.time() - 10  # Expired 10 seconds ago

    # Mock the IDP token exchange response for new ID-JAG
    new_id_jag = "new-id-jag-token"
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = httpx.Response(
            status_code=200,
            json={
                "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
                "access_token": new_id_jag,
                "token_type": "N_A",
            },
        )
        mock_client.post = AsyncMock(return_value=mock_response)

        # Should get a new ID-JAG since the cached one is expired
        request = await provider._perform_authorization()

        # Verify it made the IDP token exchange call (didn't reuse expired ID-JAG)
        mock_client.post.assert_called_once()

        # Verify the request uses the NEW ID-JAG
        body_params = urllib.parse.parse_qs(request.content.decode())
        assert body_params["assertion"][0] == new_id_jag


@pytest.mark.anyio
async def test_perform_authorization_reuses_valid_cached_id_jag(mock_token_storage: Any, sample_id_jag: str):
    """Test that _perform_authorization reuses cached ID-JAG when still valid."""
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

    # Set valid tokens and cached ID-JAG that is STILL VALID
    provider.context.current_tokens = OAuthToken(
        token_type="Bearer",
        access_token="valid-token",
        expires_in=3600,
    )
    provider.context.token_expiry_time = time.time() + 3600
    provider._id_jag = sample_id_jag
    provider._id_jag_expiry = time.time() + 300  # Valid for 5 more minutes

    # Should reuse cached ID-JAG without calling IdP
    request = await provider._perform_authorization()

    # Verify it returns a JWT bearer grant request using cached ID-JAG
    body_params = urllib.parse.parse_qs(request.content.decode())
    assert body_params["assertion"][0] == sample_id_jag


@pytest.mark.anyio
async def test_audience_override_warning(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test that audience override logs a warning when values differ."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://configured-audience.example/",  # Different from issuer
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

    # Set OAuth metadata with different issuer
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://actual-issuer.example/"),  # Different from configured
        authorization_endpoint=AnyHttpUrl("https://actual-issuer.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://actual-issuer.example/oauth2/token"),
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should log warning about audience override
    with patch.object(
        logging.getLogger("mcp.client.auth.extensions.enterprise_managed_auth"), "warning"
    ) as mock_warning:
        await provider.exchange_token_for_id_jag(mock_client)

        # Verify warning was called with message about override
        mock_warning.assert_called_once()
        warning_message = mock_warning.call_args[0][0]
        assert "Overriding audience" in warning_message
        assert "https://configured-audience.example/" in warning_message
        assert "https://actual-issuer.example/" in warning_message


@pytest.mark.anyio
async def test_audience_no_warning_when_matching(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test that no warning is logged when audience matches issuer."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",  # Same as issuer
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

    # Set OAuth metadata with matching issuer
    provider.context.oauth_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.mcp-server.example/"),  # Same as configured
        authorization_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.mcp-server.example/oauth2/token"),
    )

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Should NOT log warning when values match
    with patch.object(
        logging.getLogger("mcp.client.auth.extensions.enterprise_managed_auth"), "warning"
    ) as mock_warning:
        await provider.exchange_token_for_id_jag(mock_client)

        # Verify warning was NOT called
        mock_warning.assert_not_called()


@pytest.mark.anyio
async def test_empty_scope_not_included(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test that empty or whitespace-only scope is not included in token request."""
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example/",
        mcp_server_resource_id="https://mcp-server.example/",
        scope="   ",  # Whitespace-only scope
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

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    await provider.exchange_token_for_id_jag(mock_client)

    # Verify scope was NOT included in request
    call_args = mock_client.post.call_args
    assert "scope" not in call_args[1]["data"]


@pytest.mark.anyio
async def test_custom_default_id_jag_expiry(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test that custom default_id_jag_expiry is used when IdP doesn't provide expires_in."""
    custom_expiry = 1800  # 30 minutes

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
        default_id_jag_expiry=custom_expiry,  # Custom expiry
    )

    # Verify the custom default is set
    assert provider.default_id_jag_expiry == custom_expiry

    # Mock HTTP response WITHOUT expires_in
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
            # No expires_in field
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    before_time = time.time()
    await provider.exchange_token_for_id_jag(mock_client)
    after_time = time.time()

    # Verify custom expiry was used (1800 seconds)
    assert provider._id_jag_expiry is not None
    assert before_time + custom_expiry <= provider._id_jag_expiry <= after_time + custom_expiry


@pytest.mark.anyio
async def test_default_id_jag_expiry_constant(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test that DEFAULT_ID_JAG_EXPIRY_SECONDS class constant is used by default."""
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
        # Not providing default_id_jag_expiry, should use class constant
    )

    # Verify the class constant is used (900 seconds = 15 minutes)
    assert provider.default_id_jag_expiry == EnterpriseAuthOAuthClientProvider.DEFAULT_ID_JAG_EXPIRY_SECONDS
    assert provider.default_id_jag_expiry == 900  # 15 minutes

    # Mock HTTP response WITHOUT expires_in
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    before_time = time.time()
    await provider.exchange_token_for_id_jag(mock_client)
    after_time = time.time()

    # Verify default constant was used (900 seconds)
    assert provider._id_jag_expiry is not None
    assert before_time + 900 <= provider._id_jag_expiry <= after_time + 900


@pytest.mark.anyio
async def test_exchange_token_without_oauth_metadata(sample_id_token: str, sample_id_jag: str, mock_token_storage: Any):
    """Test token exchange when oauth_metadata is not set.

    This tests the scenario where OAuth metadata discovery hasn't happened yet.
    The configured audience from token_exchange_params should be used directly.

    Note: Testing issuer=None is not possible because OAuthMetadata.issuer is a
    required AnyHttpUrl field per RFC 8414, so the Pydantic model prevents None.
    """
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=sample_id_token,
        mcp_server_auth_issuer="https://auth.configured.example/",
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

    # No OAuth metadata set (None)
    assert provider.context.oauth_metadata is None

    # Mock HTTP response
    mock_response = httpx.Response(
        status_code=200,
        json={
            "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            "access_token": sample_id_jag,
            "token_type": "N_A",
        },
    )

    mock_client = Mock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    # Perform token exchange
    await provider.exchange_token_for_id_jag(mock_client)

    # Verify the configured audience was used (no override since metadata is None)
    call_args = mock_client.post.call_args
    assert call_args[1]["data"]["audience"] == "https://auth.configured.example/"
