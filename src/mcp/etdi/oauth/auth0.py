"""
Auth0 OAuth provider implementation for ETDI
"""

import logging
from typing import Any, Dict, List
import httpx

from .base import OAuthProvider
from ..types import OAuthConfig, VerificationResult
from ..exceptions import OAuthError, TokenValidationError

logger = logging.getLogger(__name__)


class Auth0Provider(OAuthProvider):
    """Auth0 OAuth provider implementation"""
    
    def __init__(self, config: OAuthConfig):
        super().__init__(config)
        if not config.domain:
            raise ValueError("Auth0 domain is required")
        
        # Ensure domain has proper format
        self.domain = config.domain
        if not self.domain.startswith("https://"):
            self.domain = f"https://{self.domain}"
        if not self.domain.endswith("/"):
            self.domain = f"{self.domain}/"
    
    def get_token_endpoint(self) -> str:
        """Get Auth0 token endpoint"""
        return f"{self.domain}oauth/token"
    
    def get_jwks_uri(self) -> str:
        """Get Auth0 JWKS URI"""
        return f"{self.domain}.well-known/jwks.json"
    
    def _get_expected_issuer(self) -> str:
        """Get expected token issuer for Auth0"""
        return self.domain.rstrip("/") + "/"
    
    async def get_token(self, tool_id: str, permissions: List[str]) -> str:
        """
        Get an OAuth token from Auth0 for a tool
        
        Args:
            tool_id: Unique identifier for the tool
            permissions: List of permission scopes required
            
        Returns:
            JWT token string
            
        Raises:
            OAuthError: If token acquisition fails
        """
        try:
            # Build request data
            data = {
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            }
            
            # Add audience if specified
            if self.config.audience:
                data["audience"] = self.config.audience
            
            # Add scopes
            if permissions:
                data["scope"] = " ".join(permissions)
            elif self.config.scopes:
                data["scope"] = " ".join(self.config.scopes)
            
            # Make token request
            response = await self.http_client.post(
                self.get_token_endpoint(),
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error_description", f"HTTP {response.status_code}")
                raise OAuthError(
                    f"Auth0 token request failed: {error_msg}",
                    provider=self.name,
                    oauth_error=error_data.get("error"),
                    status_code=response.status_code
                )
            
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                raise OAuthError("No access token in Auth0 response", provider=self.name)
            
            logger.info(f"Successfully obtained Auth0 token for tool {tool_id}")
            return access_token
            
        except httpx.RequestError as e:
            raise OAuthError(f"Auth0 request failed: {e}", provider=self.name)
        except Exception as e:
            if isinstance(e, OAuthError):
                raise
            raise OAuthError(f"Unexpected error getting Auth0 token: {e}", provider=self.name)
    
    async def validate_token(self, token: str, expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Validate an Auth0 JWT token
        
        Args:
            token: JWT token to validate
            expected_claims: Expected claims in the token
            
        Returns:
            VerificationResult with validation details
        """
        try:
            # Verify JWT signature and basic claims
            decoded = await self._verify_jwt_signature(token)
            
            # Validate tool-specific claims
            tool_id = expected_claims.get("toolId")
            if tool_id:
                # Check if tool_id is in subject or custom claim
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
        Get user information from Auth0 (if token represents a user)
        
        Args:
            token: Access token
            
        Returns:
            User information dictionary
        """
        try:
            response = await self.http_client.get(
                f"{self.domain}userinfo",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code != 200:
                raise OAuthError(f"Auth0 userinfo request failed: HTTP {response.status_code}", provider=self.name)
            
            return response.json()
            
        except httpx.RequestError as e:
            raise OAuthError(f"Auth0 userinfo request failed: {e}", provider=self.name)
    
    async def revoke_token(self, token: str) -> bool:
        """
        Revoke an Auth0 token
        
        Args:
            token: Token to revoke
            
        Returns:
            True if revocation was successful
        """
        try:
            response = await self.http_client.post(
                f"{self.domain}oauth/revoke",
                data={
                    "token": token,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            # Auth0 returns 200 for successful revocation
            return response.status_code == 200
            
        except httpx.RequestError as e:
            logger.warning(f"Auth0 token revocation failed: {e}")
            return False