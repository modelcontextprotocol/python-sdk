"""
Custom OAuth provider implementation for ETDI
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import httpx

from .base import OAuthProvider
from ..types import OAuthConfig, VerificationResult
from ..exceptions import OAuthError, TokenValidationError

logger = logging.getLogger(__name__)


class CustomOAuthProvider(OAuthProvider):
    """
    Base class for implementing custom OAuth providers
    
    Extend this class to implement support for custom OAuth 2.0 providers
    that are not natively supported by ETDI.
    """
    
    def __init__(self, config: OAuthConfig):
        super().__init__(config)
        self.token_endpoint = self._get_token_endpoint()
        self.jwks_uri = self._get_jwks_uri()
        self.userinfo_endpoint = self._get_userinfo_endpoint()
        self.revoke_endpoint = self._get_revoke_endpoint()
    
    @abstractmethod
    def _get_token_endpoint(self) -> str:
        """Get the OAuth token endpoint URL"""
        pass
    
    @abstractmethod
    def _get_jwks_uri(self) -> str:
        """Get the JWKS URI for token verification"""
        pass
    
    @abstractmethod
    def _get_userinfo_endpoint(self) -> str:
        """Get the userinfo endpoint URL"""
        pass
    
    @abstractmethod
    def _get_revoke_endpoint(self) -> str:
        """Get the token revocation endpoint URL"""
        pass
    
    @abstractmethod
    def _get_expected_issuer(self) -> str:
        """Get expected token issuer for this provider"""
        pass
    
    def get_token_endpoint(self) -> str:
        """Get OAuth token endpoint"""
        return self.token_endpoint
    
    def get_jwks_uri(self) -> str:
        """Get JWKS URI"""
        return self.jwks_uri
    
    async def get_token(self, tool_id: str, permissions: List[str]) -> str:
        """
        Get an OAuth token from the custom provider
        
        Args:
            tool_id: Unique identifier for the tool
            permissions: List of permission scopes required
            
        Returns:
            JWT token string
            
        Raises:
            OAuthError: If token acquisition fails
        """
        try:
            # Build request data using standard OAuth 2.0 client credentials flow
            data = self._build_token_request_data(tool_id, permissions)
            
            # Allow custom providers to modify the request data
            data = self._customize_token_request(data, tool_id, permissions)
            
            # Make token request
            response = await self.http_client.post(
                self.get_token_endpoint(),
                data=data,
                headers=self._get_token_request_headers()
            )
            
            if response.status_code != 200:
                error_data = self._parse_error_response(response)
                error_msg = error_data.get("error_description", f"HTTP {response.status_code}")
                raise OAuthError(
                    f"Custom OAuth token request failed: {error_msg}",
                    provider=self.name,
                    oauth_error=error_data.get("error"),
                    status_code=response.status_code
                )
            
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                raise OAuthError("No access token in OAuth response", provider=self.name)
            
            logger.info(f"Successfully obtained custom OAuth token for tool {tool_id}")
            return access_token
            
        except httpx.RequestError as e:
            raise OAuthError(f"Custom OAuth request failed: {e}", provider=self.name)
        except Exception as e:
            if isinstance(e, OAuthError):
                raise
            raise OAuthError(f"Unexpected error getting custom OAuth token: {e}", provider=self.name)
    
    async def validate_token(self, token: str, expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Validate a custom OAuth JWT token
        
        Args:
            token: JWT token to validate
            expected_claims: Expected claims in the token
            
        Returns:
            VerificationResult with validation details
        """
        try:
            # Verify JWT signature and basic claims
            decoded = await self._verify_jwt_signature(token)
            
            # Allow custom validation logic
            custom_validation = await self._custom_token_validation(decoded, expected_claims)
            if not custom_validation.valid:
                return custom_validation
            
            # Standard ETDI validation
            return await self._standard_etdi_validation(decoded, expected_claims)
            
        except TokenValidationError as e:
            return VerificationResult(
                valid=False,
                provider=self.name,
                error=e.message,
                details={"validation_step": e.validation_step}
            )
        except Exception as e:
            return VerificationResult(
                valid=False,
                provider=self.name,
                error=f"Unexpected validation error: {e}"
            )
    
    async def get_user_info(self, token: str) -> Dict[str, Any]:
        """
        Get user information from custom OAuth provider
        
        Args:
            token: Access token
            
        Returns:
            User information dictionary
        """
        try:
            response = await self.http_client.get(
                self.userinfo_endpoint,
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code != 200:
                raise OAuthError(f"Custom OAuth userinfo request failed: HTTP {response.status_code}", provider=self.name)
            
            return response.json()
            
        except httpx.RequestError as e:
            raise OAuthError(f"Custom OAuth userinfo request failed: {e}", provider=self.name)
    
    async def revoke_token(self, token: str) -> bool:
        """
        Revoke a custom OAuth token
        
        Args:
            token: Token to revoke
            
        Returns:
            True if revocation was successful
        """
        try:
            data = self._build_revoke_request_data(token)
            
            response = await self.http_client.post(
                self.revoke_endpoint,
                data=data,
                headers=self._get_revoke_request_headers()
            )
            
            # Most OAuth providers return 200 for successful revocation
            return response.status_code == 200
            
        except httpx.RequestError as e:
            logger.warning(f"Custom OAuth token revocation failed: {e}")
            return False
    
    def _customize_token_request(self, data: Dict[str, Any], tool_id: str, permissions: List[str]) -> Dict[str, Any]:
        """
        Customize token request data for provider-specific requirements
        
        Override this method to add provider-specific parameters
        
        Args:
            data: Base token request data
            tool_id: Tool identifier
            permissions: Required permissions
            
        Returns:
            Modified request data
        """
        return data
    
    def _get_token_request_headers(self) -> Dict[str, str]:
        """
        Get headers for token request
        
        Override this method to add provider-specific headers
        
        Returns:
            Request headers
        """
        return {"Content-Type": "application/x-www-form-urlencoded"}
    
    def _get_revoke_request_headers(self) -> Dict[str, str]:
        """
        Get headers for token revocation request
        
        Returns:
            Request headers
        """
        return {"Content-Type": "application/x-www-form-urlencoded"}
    
    def _build_revoke_request_data(self, token: str) -> Dict[str, str]:
        """
        Build token revocation request data
        
        Args:
            token: Token to revoke
            
        Returns:
            Request data
        """
        return {
            "token": token,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret
        }
    
    def _parse_error_response(self, response: httpx.Response) -> Dict[str, Any]:
        """
        Parse error response from OAuth provider
        
        Args:
            response: HTTP response
            
        Returns:
            Parsed error data
        """
        try:
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
        except Exception:
            pass
        
        return {"error": "unknown_error", "error_description": response.text}
    
    async def _custom_token_validation(self, decoded: Dict[str, Any], expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Perform custom token validation logic
        
        Override this method to implement provider-specific validation
        
        Args:
            decoded: Decoded JWT claims
            expected_claims: Expected claims
            
        Returns:
            Validation result
        """
        # Default implementation - no custom validation
        return VerificationResult(valid=True, provider=self.name)
    
    async def _standard_etdi_validation(self, decoded: Dict[str, Any], expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Perform standard ETDI token validation
        
        Args:
            decoded: Decoded JWT claims
            expected_claims: Expected claims
            
        Returns:
            Validation result
        """
        # Validate tool-specific claims
        tool_id = expected_claims.get("toolId")
        if tool_id:
            token_tool_id = decoded.get("tool_id") or decoded.get("sub")
            if token_tool_id != tool_id:
                return VerificationResult(
                    valid=False,
                    provider=self.name,
                    error=f"Token tool_id mismatch: expected {tool_id}, got {token_tool_id}"
                )
        
        # Validate tool version if specified
        tool_version = expected_claims.get("toolVersion")
        if tool_version:
            token_version = decoded.get("tool_version")
            if token_version and token_version != tool_version:
                return VerificationResult(
                    valid=False,
                    provider=self.name,
                    error=f"Token version mismatch: expected {tool_version}, got {token_version}"
                )
        
        # Validate required permissions/scopes
        required_permissions = expected_claims.get("requiredPermissions", [])
        if required_permissions:
            token_scope = decoded.get("scope", "")
            token_scopes = set(token_scope.split()) if token_scope else set()
            required_scopes = set(required_permissions)
            
            missing_scopes = required_scopes - token_scopes
            if missing_scopes:
                return VerificationResult(
                    valid=False,
                    provider=self.name,
                    error=f"Missing required scopes: {', '.join(missing_scopes)}"
                )
        
        # Validate audience if specified in config
        if self.config.audience:
            token_aud = decoded.get("aud")
            if isinstance(token_aud, list):
                if self.config.audience not in token_aud:
                    return VerificationResult(
                        valid=False,
                        provider=self.name,
                        error=f"Token audience mismatch: {self.config.audience} not in {token_aud}"
                    )
            elif token_aud != self.config.audience:
                return VerificationResult(
                    valid=False,
                    provider=self.name,
                    error=f"Token audience mismatch: expected {self.config.audience}, got {token_aud}"
                )
        
        return VerificationResult(
            valid=True,
            provider=self.name,
            details={
                "issuer": decoded.get("iss"),
                "subject": decoded.get("sub"),
                "audience": decoded.get("aud"),
                "scopes": decoded.get("scope", "").split(),
                "expires_at": decoded.get("exp"),
                "issued_at": decoded.get("iat"),
                "tool_id": decoded.get("tool_id"),
                "tool_version": decoded.get("tool_version")
            }
        )


class GenericOAuthProvider(CustomOAuthProvider):
    """
    Generic OAuth provider implementation for standard OAuth 2.0 providers
    
    This can be used for any OAuth 2.0 provider that follows standard conventions.
    """
    
    def __init__(self, config: OAuthConfig, endpoints: Dict[str, str]):
        """
        Initialize generic OAuth provider
        
        Args:
            config: OAuth configuration
            endpoints: Dictionary with endpoint URLs:
                - token_endpoint: OAuth token endpoint
                - jwks_uri: JWKS URI for token verification
                - userinfo_endpoint: Userinfo endpoint
                - revoke_endpoint: Token revocation endpoint
                - issuer: Expected token issuer
        """
        self.endpoints = endpoints
        super().__init__(config)
    
    def _get_token_endpoint(self) -> str:
        return self.endpoints["token_endpoint"]
    
    def _get_jwks_uri(self) -> str:
        return self.endpoints["jwks_uri"]
    
    def _get_userinfo_endpoint(self) -> str:
        return self.endpoints["userinfo_endpoint"]
    
    def _get_revoke_endpoint(self) -> str:
        return self.endpoints["revoke_endpoint"]
    
    def _get_expected_issuer(self) -> str:
        return self.endpoints["issuer"]