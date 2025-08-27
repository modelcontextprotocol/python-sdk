"""
Tests for the TokenHandler class.
"""

import base64
import time
from collections.abc import Callable
from typing import Any, cast
from unittest import mock

import pytest
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.types import Scope

from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class MockOAuthProvider(OAuthAuthorizationServerProvider[Any, Any, Any]):
    """Mock OAuth provider for testing TokenHandler."""
    
    def __init__(self):
        self.auth_codes: dict[str, Any] = {}
        self.refresh_tokens: dict[str, Any] = {}
        self.tokens: dict[str, Any] = {}
    
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Mock client lookup."""
        if client_id == "test_client":
            return OAuthClientInformationFull(
                client_id="test_client",
                client_secret="test_secret",
                redirect_uris=[AnyUrl("https://client.example.com/callback")],
                grant_types=["authorization_code", "refresh_token"],
            )
        return None
    
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Any | None:
        """Mock authorization code loading."""
        return self.auth_codes.get(authorization_code)
    
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: Any
    ) -> OAuthToken:
        """Mock authorization code exchange."""
        return OAuthToken(
            access_token="test_access_token",
            token_type="Bearer",
            expires_in=3600,
            scope="read write",
            refresh_token="test_refresh_token",
        )
    
    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> Any | None:
        """Mock refresh token loading."""
        return self.refresh_tokens.get(refresh_token)
    
    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: Any, scopes: list[str]
    ) -> OAuthToken:
        """Mock refresh token exchange."""
        return OAuthToken(
            access_token="new_access_token",
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes),
            refresh_token="new_refresh_token",
        )
    
    # Implement required abstract methods with correct signatures
    async def register_client(self, client_info: Any) -> None:
        """Mock client registration."""
        pass
    
    async def authorize(self, client: OAuthClientInformationFull, params: Any) -> str:
        """Mock authorization."""
        return "mock_auth_code"
    
    async def load_access_token(self, token: str) -> Any | None:
        """Mock access token loading."""
        return None
    
    async def revoke_token(self, token: str) -> None:
        """Mock token revocation."""
        pass


class MockClientAuthenticator(ClientAuthenticator):
    """Mock client authenticator for testing."""
    
    def __init__(self, provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        super().__init__(provider)
    
    async def authenticate(self, client_id: str, client_secret: str | None) -> OAuthClientInformationFull:
        """Mock authentication."""
        client = await self.provider.get_client(client_id)
        if not client:
            raise AuthenticationError("Invalid client_id")
        
        if client.client_secret and client.client_secret != client_secret:
            raise AuthenticationError("Invalid client_secret")
        
        return client


@pytest.fixture
def mock_provider() -> MockOAuthProvider:
    """Create a mock OAuth provider."""
    return MockOAuthProvider()


@pytest.fixture
def mock_authenticator(mock_provider: MockOAuthProvider) -> MockClientAuthenticator:
    """Create a mock client authenticator."""
    return MockClientAuthenticator(mock_provider)


@pytest.fixture
def token_handler(mock_provider: MockOAuthProvider, mock_authenticator: MockClientAuthenticator) -> TokenHandler:
    """Create a TokenHandler instance for testing."""
    return TokenHandler(provider=mock_provider, client_authenticator=mock_authenticator)


@pytest.fixture
def mock_request() -> Callable[..., Request]:
    """Create a mock request object."""
    def _create_request(
        *, 
        method: str = "POST", 
        headers: dict[str, str] | None = None, 
        form_data: dict[str, str] | None = None
    ) -> Request:
        scope: Scope = {
            "type": "http",
            "method": method,
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        }
        
        request = Request(scope)
        
        # Mock the form method with proper signature
        async def mock_form(
            *, 
            max_files: int | float = 1000, 
            max_fields: int | float = 1000, 
            max_part_size: int = 1024 * 1024
        ) -> dict[str, str]:
            return form_data or {}
        
        # Use monkey patching to avoid type issues
        request.form = mock_form  # type: ignore
        return request
    
    return _create_request


class TestTokenHandler:
    """Test cases for TokenHandler."""
    
    @pytest.mark.anyio
    async def test_handle_with_form_data_credentials(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that credentials from form data are used correctly."""
        # Set up mock auth code
        auth_code = mock.MagicMock()
        auth_code.client_id = "test_client"
        auth_code.expires_at = time.time() + 300  # 5 minutes from now
        auth_code.redirect_uri_provided_explicitly = False
        auth_code.redirect_uri = None
        auth_code.code_challenge = "test_challenge"
        auth_code.scopes = ["read", "write"]
        
        # Cast to access the custom attribute
        provider = cast(MockOAuthProvider, token_handler.provider)
        provider.auth_codes["test_code"] = auth_code
        
        # Create request with form data credentials
        request = mock_request(
            method="POST",
            form_data={
                "grant_type": "authorization_code",
                "code": "test_code",
                "client_id": "test_client",
                "client_secret": "test_secret",
                "code_verifier": "test_verifier",
            }
        )
        
        # Mock the code verifier hash
        with mock.patch("hashlib.sha256") as mock_sha256:
            mock_sha256.return_value.digest.return_value = b"test_hash"
            with mock.patch("base64.urlsafe_b64encode") as mock_b64encode:
                mock_b64encode.return_value.decode.return_value.rstrip.return_value = "test_challenge"
                
                response = await token_handler.handle(request)
                
                assert response.status_code == 200
                content = response.body.decode()  # type: ignore
                assert "access_token" in content
    
    @pytest.mark.anyio
    async def test_handle_with_authorization_header_credentials(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that credentials from Authorization header are used as fallback."""
        # Set up mock auth code
        auth_code = mock.MagicMock()
        auth_code.client_id = "test_client"
        auth_code.expires_at = time.time() + 300  # 5 minutes from now
        auth_code.redirect_uri_provided_explicitly = False
        auth_code.redirect_uri = None
        auth_code.code_challenge = "test_challenge"
        auth_code.scopes = ["read", "write"]
        
        # Cast to access the custom attribute
        provider = cast(MockOAuthProvider, token_handler.provider)
        provider.auth_codes["test_code"] = auth_code
        
        # Create Basic Auth header
        credentials = "test_client:test_secret"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        # Create request with Authorization header but no form credentials
        request = mock_request(
            method="POST",
            headers={"Authorization": f"Basic {encoded_credentials}"},
            form_data={
                "grant_type": "authorization_code",
                "code": "test_code",
                "code_verifier": "test_verifier",
                # client_id and client_secret missing from form data
            }
        )
        
        # Mock the code verifier hash
        with mock.patch("hashlib.sha256") as mock_sha256:
            mock_sha256.return_value.digest.return_value = b"test_hash"
            with mock.patch("base64.urlsafe_b64encode") as mock_b64encode:
                mock_b64encode.return_value.decode.return_value.rstrip.return_value = "test_challenge"
                
                response = await token_handler.handle(request)
                
                assert response.status_code == 200
                content = response.body.decode()  # type: ignore
                assert "access_token" in content
    
    @pytest.mark.anyio
    async def test_handle_with_authorization_header_url_encoded_secret(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that URL-encoded client secrets in Authorization header are handled correctly."""
        # Set up mock auth code
        auth_code = mock.MagicMock()
        auth_code.client_id = "test_client"
        auth_code.expires_at = time.time() + 300  # 5 minutes from now
        auth_code.redirect_uri_provided_explicitly = False
        auth_code.redirect_uri = None
        auth_code.code_challenge = "test_challenge"
        auth_code.scopes = ["read", "write"]
        
        # Cast to access the custom attribute
        provider = cast(MockOAuthProvider, token_handler.provider)
        provider.auth_codes["test_code"] = auth_code
        
        # Create Basic Auth header with URL-encoded secret
        credentials = "test_client:test%2Bsecret"  # URL-encoded "test+secret"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        # Create request with Authorization header but no form credentials
        request = mock_request(
            method="POST",
            headers={"Authorization": f"Basic {encoded_credentials}"},
            form_data={
                "grant_type": "authorization_code",
                "code": "test_code",
                "code_verifier": "test_verifier",
                # client_id and client_secret missing from form data
            }
        )
        
        # Mock the code verifier hash
        with mock.patch("hashlib.sha256") as mock_sha256:
            mock_sha256.return_value.digest.return_value = b"test_hash"
            with mock.patch("base64.urlsafe_b64encode") as mock_b64encode:
                mock_b64encode.return_value.decode.return_value.rstrip.return_value = "test_challenge"
                
                # Mock the provider to return a client with the URL-decoded secret
                with mock.patch.object(token_handler.provider, 'get_client') as mock_get_client:
                    mock_get_client.return_value = OAuthClientInformationFull(
                        client_id="test_client",
                        client_secret="test+secret",  # URL-decoded version
                        redirect_uris=[AnyUrl("https://client.example.com/callback")],
                        grant_types=["authorization_code", "refresh_token"],
                    )
                    
                    response = await token_handler.handle(request)
                    
                    assert response.status_code == 200
                    content = response.body.decode()  # type: ignore
                    assert "access_token" in content
    
    @pytest.mark.anyio
    async def test_handle_with_invalid_authorization_header(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that invalid Authorization header doesn't break the flow."""
        # Set up mock auth code
        auth_code = mock.MagicMock()
        auth_code.client_id = "test_client"
        auth_code.expires_at = time.time() + 300  # 5 minutes from now
        auth_code.redirect_uri_provided_explicitly = False
        auth_code.redirect_uri = None
        auth_code.code_challenge = "test_challenge"
        auth_code.scopes = ["read", "write"]
        
        # Cast to access the custom attribute
        provider = cast(MockOAuthProvider, token_handler.provider)
        provider.auth_codes["test_code"] = auth_code
        
        # Create request with invalid Authorization header
        request = mock_request(
            method="POST",
            headers={"Authorization": "InvalidHeader"},
            form_data={
                "grant_type": "authorization_code",
                "code": "test_code",
                "client_id": "test_client",
                "client_secret": "test_secret",
                "code_verifier": "test_verifier",
            }
        )
        
        # Mock the code verifier hash
        with mock.patch("hashlib.sha256") as mock_sha256:
            mock_sha256.return_value.digest.return_value = b"test_hash"
            with mock.patch("base64.urlsafe_b64encode") as mock_b64encode:
                mock_b64encode.return_value.decode.return_value.rstrip.return_value = "test_challenge"
                
                response = await token_handler.handle(request)
                
                # Should still work since form data has credentials
                assert response.status_code == 200
                content = response.body.decode()  # type: ignore
                assert "access_token" in content
    
    @pytest.mark.anyio
    async def test_handle_with_malformed_basic_auth(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that malformed Basic Auth header doesn't break the flow."""
        # Set up mock auth code
        auth_code = mock.MagicMock()
        auth_code.client_id = "test_client"
        auth_code.expires_at = time.time() + 300  # 5 minutes from now
        auth_code.redirect_uri_provided_explicitly = False
        auth_code.redirect_uri = None
        auth_code.code_challenge = "test_challenge"
        auth_code.scopes = ["read", "write"]
        
        # Cast to access the custom attribute
        provider = cast(MockOAuthProvider, token_handler.provider)
        provider.auth_codes["test_code"] = auth_code
        
        # Create request with malformed Basic Auth header
        request = mock_request(
            method="POST",
            headers={"Authorization": "Basic invalid_base64"},
            form_data={
                "grant_type": "authorization_code",
                "code": "test_code",
                "client_id": "test_client",
                "client_secret": "test_secret",
                "code_verifier": "test_verifier",
            }
        )
        
        # Mock the code verifier hash
        with mock.patch("hashlib.sha256") as mock_sha256:
            mock_sha256.return_value.digest.return_value = b"test_hash"
            with mock.patch("base64.urlsafe_b64encode") as mock_b64encode:
                mock_b64encode.return_value.decode.return_value.rstrip.return_value = "test_challenge"
                
                response = await token_handler.handle(request)
                
                # Should still work since form data has credentials
                assert response.status_code == 200
                content = response.body.decode()  # type: ignore
                assert "access_token" in content
    
    @pytest.mark.anyio
    async def test_handle_with_refresh_token_grant(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that refresh token grant works with Authorization header fallback."""
        # Set up mock refresh token
        refresh_token = mock.MagicMock()
        refresh_token.client_id = "test_client"
        refresh_token.expires_at = time.time() + 3600  # 1 hour from now
        refresh_token.scopes = ["read", "write"]
        
        # Cast to access the custom attribute
        provider = cast(MockOAuthProvider, token_handler.provider)
        provider.refresh_tokens["test_refresh_token"] = refresh_token
        
        # Create Basic Auth header
        credentials = "test_client:test_secret"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        # Create request with refresh token grant
        request = mock_request(
            method="POST",
            headers={"Authorization": f"Basic {encoded_credentials}"},
            form_data={
                "grant_type": "refresh_token",
                "refresh_token": "test_refresh_token",
                # client_id and client_secret missing from form data
            }
        )
        
        response = await token_handler.handle(request)
        
        assert response.status_code == 200
        content = response.body.decode()  # type: ignore
        assert "access_token" in content
    
    @pytest.mark.anyio
    async def test_handle_without_credentials_fails(
        self, 
        token_handler: TokenHandler, 
        mock_request: Callable[..., Request]
    ) -> None:
        """Test that request without credentials fails validation."""
        # Create request without any credentials
        request = mock_request(
            method="POST",
            form_data={
                "grant_type": "authorization_code",
                "code": "test_code",
                "code_verifier": "test_verifier",
                # No client_id or client_secret anywhere
            }
        )
        
        response = await token_handler.handle(request)
        
        assert response.status_code == 400
        content = response.body.decode()  # type: ignore
        assert "invalid_request" in content
