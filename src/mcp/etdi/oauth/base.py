"""
Base OAuth provider interface and manager for ETDI
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
import httpx
import jwt
from jwt import PyJWKClient

from ..types import OAuthConfig, VerificationResult
from ..exceptions import OAuthError, ProviderError, TokenValidationError

logger = logging.getLogger(__name__)


class OAuthProvider(ABC):
    """Abstract base class for OAuth providers"""
    
    def __init__(self, config: OAuthConfig):
        self.config = config
        self.name = config.provider
        self._http_client: Optional[httpx.AsyncClient] = None
        self._jwks_client: Optional[PyJWKClient] = None
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def initialize(self) -> None:
        """Initialize the OAuth provider"""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._jwks_client = PyJWKClient(self.get_jwks_uri())
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        if self._http_client:
            await self._http_client.aclose()
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get HTTP client, initializing if needed"""
        if self._http_client is None:
            # Check if we're in a test environment by looking for mock attributes
            if hasattr(self, '_test_http_client'):
                return self._test_http_client
            raise RuntimeError("OAuth provider not initialized. Call initialize() first.")
        return self._http_client
    
    @property
    def jwks_client(self) -> PyJWKClient:
        """Get JWKS client, initializing if needed"""
        if self._jwks_client is None:
            raise RuntimeError("OAuth provider not initialized. Call initialize() first.")
        return self._jwks_client
    
    @abstractmethod
    def get_token_endpoint(self) -> str:
        """Get the OAuth token endpoint URL"""
        pass
    
    @abstractmethod
    def get_jwks_uri(self) -> str:
        """Get the JWKS URI for token verification"""
        pass
    
    @abstractmethod
    async def get_token(self, tool_id: str, permissions: List[str]) -> str:
        """
        Get an OAuth token for a tool with specified permissions
        
        Args:
            tool_id: Unique identifier for the tool
            permissions: List of permission scopes required
            
        Returns:
            JWT token string
            
        Raises:
            OAuthError: If token acquisition fails
        """
        pass
    
    @abstractmethod
    async def validate_token(self, token: str, expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Validate an OAuth token
        
        Args:
            token: JWT token to validate
            expected_claims: Expected claims in the token
            
        Returns:
            VerificationResult with validation details
        """
        pass
    
    async def refresh_token(self, token: str) -> str:
        """
        Refresh an OAuth token (default implementation)
        
        Args:
            token: Existing token to refresh
            
        Returns:
            New JWT token string
            
        Raises:
            OAuthError: If token refresh fails
        """
        # Default implementation - decode token to get tool info and re-request
        try:
            # Decode without verification to get claims
            decoded = jwt.decode(token, options={"verify_signature": False})
            tool_id = decoded.get("tool_id") or decoded.get("sub")
            scopes = decoded.get("scope", "").split() if decoded.get("scope") else []
            
            if not tool_id:
                raise OAuthError("Cannot refresh token: missing tool_id in token", provider=self.name)
            
            return await self.get_token(tool_id, scopes)
            
        except jwt.DecodeError as e:
            raise OAuthError(f"Cannot refresh token: invalid JWT format: {e}", provider=self.name)
    
    async def introspect_token(self, token: str) -> Dict[str, Any]:
        """
        Introspect a token to get its metadata
        
        Args:
            token: JWT token to introspect
            
        Returns:
            Token metadata dictionary
        """
        try:
            # Basic JWT decode without signature verification for introspection
            decoded = jwt.decode(token, options={"verify_signature": False})
            return decoded
        except jwt.DecodeError as e:
            raise TokenValidationError(f"Invalid JWT format: {e}", provider=self.name)
    
    def _build_token_request_data(self, tool_id: str, permissions: List[str]) -> Dict[str, Any]:
        """Build token request data (common implementation)"""
        scope = " ".join(permissions) if permissions else ""
        
        return {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": scope,
            "audience": self.config.audience or "",
            # Custom claims for tool identification
            "tool_id": tool_id,
        }
    
    async def _verify_jwt_signature(self, token: str) -> Dict[str, Any]:
        """Verify JWT signature using JWKS"""
        try:
            # Get signing key from JWKS
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            
            # Verify and decode token
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "HS256"],
                audience=self.config.audience,
                issuer=self._get_expected_issuer()
            )
            
            return decoded
            
        except jwt.ExpiredSignatureError:
            raise TokenValidationError("Token has expired", provider=self.name, validation_step="signature")
        except jwt.InvalidAudienceError:
            raise TokenValidationError("Invalid token audience", provider=self.name, validation_step="signature")
        except jwt.InvalidIssuerError:
            raise TokenValidationError("Invalid token issuer", provider=self.name, validation_step="signature")
        except jwt.InvalidSignatureError:
            raise TokenValidationError("Invalid token signature", provider=self.name, validation_step="signature")
        except Exception as e:
            raise TokenValidationError(f"Token verification failed: {e}", provider=self.name, validation_step="signature")
    
    @abstractmethod
    def _get_expected_issuer(self) -> str:
        """Get expected token issuer for this provider"""
        pass


class OAuthManager:
    """Manages multiple OAuth providers and token operations"""
    
    def __init__(self, providers: Optional[Dict[str, OAuthProvider]] = None):
        self.providers: Dict[str, OAuthProvider] = providers or {}
        self._token_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
    
    def register_provider(self, name: str, provider: OAuthProvider) -> None:
        """Register an OAuth provider"""
        self.providers[name] = provider
    
    def get_provider(self, name: str) -> Optional[OAuthProvider]:
        """Get an OAuth provider by name"""
        return self.providers.get(name)
    
    def list_providers(self) -> List[str]:
        """List available provider names"""
        return list(self.providers.keys())
    
    async def initialize_all(self) -> None:
        """Initialize all registered providers"""
        for provider in self.providers.values():
            await provider.initialize()
    
    async def cleanup_all(self) -> None:
        """Cleanup all registered providers"""
        for provider in self.providers.values():
            await provider.cleanup()
    
    async def get_token(self, provider_name: str, tool_id: str, permissions: List[str]) -> str:
        """
        Get a token from a specific provider
        
        Args:
            provider_name: Name of the OAuth provider
            tool_id: Tool identifier
            permissions: Required permissions
            
        Returns:
            JWT token string
            
        Raises:
            ProviderError: If provider not found
            OAuthError: If token acquisition fails
        """
        provider = self.get_provider(provider_name)
        if not provider:
            available = ", ".join(self.list_providers())
            raise ProviderError(
                f"OAuth provider '{provider_name}' not found. Available: {available}",
                provider=provider_name
            )
        
        # Check cache first
        cache_key = f"{provider_name}:{tool_id}:{':'.join(sorted(permissions))}"
        async with self._cache_lock:
            cached = self._token_cache.get(cache_key)
            if cached and cached["expires_at"] > datetime.now():
                return cached["token"]
        
        # Get new token
        token = await provider.get_token(tool_id, permissions)
        
        # Cache token (extract expiration from JWT)
        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp = decoded.get("exp")
            expires_at = datetime.fromtimestamp(exp) if exp else datetime.now() + timedelta(hours=1)
            
            async with self._cache_lock:
                self._token_cache[cache_key] = {
                    "token": token,
                    "expires_at": expires_at
                }
        except Exception:
            # If we can't decode, just don't cache
            pass
        
        return token
    
    async def validate_token(self, provider_name: str, token: str, expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Validate a token using a specific provider
        
        Args:
            provider_name: Name of the OAuth provider
            token: JWT token to validate
            expected_claims: Expected claims in the token
            
        Returns:
            VerificationResult
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return VerificationResult(
                valid=False,
                provider=provider_name,
                error=f"Provider '{provider_name}' not found"
            )
        
        return await provider.validate_token(token, expected_claims)
    
    async def refresh_token(self, provider_name: str, token: str) -> str:
        """
        Refresh a token using a specific provider
        
        Args:
            provider_name: Name of the OAuth provider
            token: Token to refresh
            
        Returns:
            New JWT token string
        """
        provider = self.get_provider(provider_name)
        if not provider:
            raise ProviderError(f"OAuth provider '{provider_name}' not found", provider=provider_name)
        
        return await provider.refresh_token(token)
    
    def clear_cache(self) -> None:
        """Clear the token cache"""
        self._token_cache.clear()
    
    async def __aenter__(self):
        await self.initialize_all()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_all()