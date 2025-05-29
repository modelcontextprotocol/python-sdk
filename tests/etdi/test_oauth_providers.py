"""
Tests for ETDI OAuth providers
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from mcp.etdi.oauth import Auth0Provider, OktaProvider, AzureADProvider
from mcp.etdi.types import OAuthConfig, VerificationResult
from mcp.etdi.exceptions import OAuthError, TokenValidationError


@pytest.fixture
def auth0_config():
    return OAuthConfig(
        provider="auth0",
        client_id="test-client-id",
        client_secret="test-client-secret",
        domain="test.auth0.com",
        audience="https://test-api.example.com",
        scopes=["read:tools", "execute:tools"]
    )


@pytest.fixture
def okta_config():
    return OAuthConfig(
        provider="okta",
        client_id="test-client-id",
        client_secret="test-client-secret",
        domain="test.okta.com",
        scopes=["etdi.tools.read", "etdi.tools.execute"]
    )


@pytest.fixture
def azure_config():
    return OAuthConfig(
        provider="azure",
        client_id="test-client-id",
        client_secret="test-client-secret",
        domain="test-tenant-id",
        scopes=["https://graph.microsoft.com/.default"]
    )


@pytest.fixture
def mock_jwt_token():
    return "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJpYXQiOjE2MzQ1NjcwMDAsImV4cCI6MTYzNDU3MDYwMCwic2NvcGUiOiJyZWFkOnRvb2xzIGV4ZWN1dGU6dG9vbHMiLCJ0b29sX2lkIjoidGVzdC10b29sIiwidG9vbF92ZXJzaW9uIjoiMS4wLjAifQ.signature"


class TestAuth0Provider:
    """Test Auth0 OAuth provider"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, auth0_config):
        """Test Auth0 provider initialization"""
        provider = Auth0Provider(auth0_config)
        
        assert provider.name == "auth0"
        assert provider.config == auth0_config
        assert provider.domain == "https://test.auth0.com/"
    
    def test_endpoints(self, auth0_config):
        """Test Auth0 endpoint URLs"""
        provider = Auth0Provider(auth0_config)
        
        assert provider.get_token_endpoint() == "https://test.auth0.com/oauth/token"
        assert provider.get_jwks_uri() == "https://test.auth0.com/.well-known/jwks.json"
        assert provider._get_expected_issuer() == "https://test.auth0.com/"
    
    @pytest.mark.asyncio
    async def test_get_token_success(self, auth0_config, mock_jwt_token):
        """Test successful token acquisition"""
        provider = Auth0Provider(auth0_config)
        
        # Mock HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": mock_jwt_token}
        
        # Set up mock client directly
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._test_http_client = mock_client
        
        token = await provider.get_token("test-tool", ["read:tools"])
        
        assert token == mock_jwt_token
        mock_client.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_token_failure(self, auth0_config):
        """Test token acquisition failure"""
        provider = Auth0Provider(auth0_config)
        
        # Mock HTTP client with error response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_client",
            "error_description": "Invalid client credentials"
        }
        mock_response.headers = {"content-type": "application/json"}
        
        # Set up mock client directly
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._test_http_client = mock_client
        
        with pytest.raises(OAuthError) as exc_info:
            await provider.get_token("test-tool", ["read:tools"])
            
            assert "Auth0 token request failed" in str(exc_info.value)
            assert exc_info.value.oauth_error == "invalid_client"
    
    @pytest.mark.asyncio
    async def test_validate_token_success(self, auth0_config):
        """Test successful token validation"""
        provider = Auth0Provider(auth0_config)
        
        # Mock JWT verification
        mock_decoded = {
            "iss": "https://test.auth0.com/",
            "sub": "test-tool",
            "aud": "https://test-api.example.com",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
            "iat": int(datetime.now().timestamp()),
            "scope": "read:tools execute:tools",
            "tool_id": "test-tool",
            "tool_version": "1.0.0"
        }
        
        with patch.object(provider, '_verify_jwt_signature', return_value=mock_decoded):
            result = await provider.validate_token(
                "mock-token",
                {
                    "toolId": "test-tool",
                    "toolVersion": "1.0.0",
                    "requiredPermissions": ["read:tools"]
                }
            )
            
            assert result.valid is True
            assert result.provider == "auth0"
            assert result.details["tool_id"] == "test-tool"
    
    @pytest.mark.asyncio
    async def test_validate_token_tool_mismatch(self, auth0_config):
        """Test token validation with tool ID mismatch"""
        provider = Auth0Provider(auth0_config)
        
        mock_decoded = {
            "iss": "https://test.auth0.com/",
            "sub": "different-tool",
            "aud": "https://test-api.example.com",
            "scope": "read:tools",
            "tool_id": "different-tool"
        }
        
        with patch.object(provider, '_verify_jwt_signature', return_value=mock_decoded):
            result = await provider.validate_token(
                "mock-token",
                {"toolId": "test-tool"}
            )
            
            assert result.valid is False
            assert "tool_id mismatch" in result.error


class TestOktaProvider:
    """Test Okta OAuth provider"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, okta_config):
        """Test Okta provider initialization"""
        provider = OktaProvider(okta_config)
        
        assert provider.name == "okta"
        assert provider.config == okta_config
        assert provider.domain == "https://test.okta.com/"
    
    def test_endpoints(self, okta_config):
        """Test Okta endpoint URLs"""
        provider = OktaProvider(okta_config)
        
        assert provider.get_token_endpoint() == "https://test.okta.com/oauth2/default/v1/token"
        assert provider.get_jwks_uri() == "https://test.okta.com/oauth2/default/v1/keys"
        assert provider._get_expected_issuer() == "https://test.okta.com/oauth2/default"
    
    @pytest.mark.asyncio
    async def test_validate_token_with_scopes_array(self, okta_config):
        """Test token validation with scopes as array (Okta format)"""
        provider = OktaProvider(okta_config)
        
        mock_decoded = {
            "iss": "https://test.okta.com/oauth2/default",
            "sub": "test-tool",
            "cid": "test-client-id",
            "scp": ["etdi.tools.read", "etdi.tools.execute"],  # Okta uses array format
            "tool_id": "test-tool"
        }
        
        with patch.object(provider, '_verify_jwt_signature', return_value=mock_decoded):
            result = await provider.validate_token(
                "mock-token",
                {
                    "toolId": "test-tool",
                    "requiredPermissions": ["etdi.tools.read"]
                }
            )
            
            assert result.valid is True
            assert result.details["scopes"] == ["etdi.tools.read", "etdi.tools.execute"]


class TestAzureADProvider:
    """Test Azure AD OAuth provider"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, azure_config):
        """Test Azure AD provider initialization"""
        provider = AzureADProvider(azure_config)
        
        assert provider.name == "azure"
        assert provider.config == azure_config
        assert provider.tenant_id == "test-tenant-id"
        assert provider.base_url == "https://login.microsoftonline.com/test-tenant-id"
    
    def test_endpoints(self, azure_config):
        """Test Azure AD endpoint URLs"""
        provider = AzureADProvider(azure_config)
        
        assert provider.get_token_endpoint() == "https://login.microsoftonline.com/test-tenant-id/oauth2/v2.0/token"
        assert provider.get_jwks_uri() == "https://login.microsoftonline.com/test-tenant-id/discovery/v2.0/keys"
        assert provider._get_expected_issuer() == "https://login.microsoftonline.com/test-tenant-id/v2.0"
    
    @pytest.mark.asyncio
    async def test_get_token_with_custom_scopes(self, azure_config, mock_jwt_token):
        """Test token acquisition with custom scope formatting"""
        provider = AzureADProvider(azure_config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": mock_jwt_token}
        
        # Set up mock client directly
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._test_http_client = mock_client
        
        # Test with custom permissions that should be formatted
        await provider.get_token("test-tool", ["read:data", "write:data"])
        
        # Verify the call was made with properly formatted scopes
        call_args = mock_client.post.call_args
        data = call_args[1]['data']
        
        # Should format custom scopes with app ID prefix
        expected_scopes = [
            f"api://{azure_config.client_id}/read:data",
            f"api://{azure_config.client_id}/write:data"
        ]
        assert data['scope'] == " ".join(expected_scopes)
    
    @pytest.mark.asyncio
    async def test_validate_token_azure_claims(self, azure_config):
        """Test token validation with Azure-specific claims"""
        provider = AzureADProvider(azure_config)
        
        mock_decoded = {
            "iss": "https://login.microsoftonline.com/test-tenant-id/v2.0",
            "sub": "test-tool",
            "appid": "test-client-id",
            "tid": "test-tenant-id",
            "scp": "read:data write:data",  # Azure uses space-separated string
            "tool_id": "test-tool",
            "oid": "object-id",
            "ver": "2.0"
        }
        
        with patch.object(provider, '_verify_jwt_signature', return_value=mock_decoded):
            result = await provider.validate_token(
                "mock-token",
                {
                    "toolId": "test-tool",
                    "requiredPermissions": ["read:data"]
                }
            )
            
            assert result.valid is True
            assert result.details["application_id"] == "test-client-id"
            assert result.details["tenant_id"] == "test-tenant-id"
            assert result.details["scopes"] == ["read:data", "write:data"]


@pytest.mark.asyncio
async def test_provider_context_manager(auth0_config):
    """Test provider context manager functionality"""
    provider = Auth0Provider(auth0_config)
    
    # Mock the HTTP client initialization
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        async with provider:
            assert provider._http_client is not None
        
        # Verify cleanup was called
        mock_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_provider_token_refresh(auth0_config, mock_jwt_token):
    """Test token refresh functionality"""
    provider = Auth0Provider(auth0_config)
    
    # Mock JWT decode for refresh
    with patch('jwt.decode') as mock_decode:
        mock_decode.return_value = {
            "tool_id": "test-tool",
            "scope": "read:tools execute:tools"
        }
        
        # Mock get_token method
        with patch.object(provider, 'get_token', return_value="new-token") as mock_get_token:
            new_token = await provider.refresh_token(mock_jwt_token)
            
            assert new_token == "new-token"
            mock_get_token.assert_called_once_with("test-tool", ["read:tools", "execute:tools"])


@pytest.mark.asyncio
async def test_provider_introspect_token(auth0_config, mock_jwt_token):
    """Test token introspection"""
    provider = Auth0Provider(auth0_config)
    
    with patch('jwt.decode') as mock_decode:
        mock_decode.return_value = {
            "iss": "https://test.auth0.com/",
            "sub": "test-tool",
            "exp": 1634570600,
            "iat": 1634567000
        }
        
        result = await provider.introspect_token(mock_jwt_token)
        
        assert result["sub"] == "test-tool"
        assert result["iss"] == "https://test.auth0.com/"