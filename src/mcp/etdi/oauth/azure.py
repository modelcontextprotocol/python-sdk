"""
Azure AD OAuth provider implementation for ETDI
"""

import logging
from typing import Any, Dict, List
import httpx

from .base import OAuthProvider
from ..types import OAuthConfig, VerificationResult
from ..exceptions import OAuthError, TokenValidationError

logger = logging.getLogger(__name__)


class AzureADProvider(OAuthProvider):
    """Azure AD OAuth provider implementation"""
    
    def __init__(self, config: OAuthConfig):
        super().__init__(config)
        if not config.domain:
            raise ValueError("Azure AD tenant ID or domain is required")
        
        # Support both tenant ID and custom domain
        self.tenant_id = config.domain
        if self.tenant_id.endswith(".onmicrosoft.com"):
            # Extract tenant ID from domain
            self.tenant_id = self.tenant_id.replace(".onmicrosoft.com", "")
        
        # Azure AD endpoints
        self.base_url = f"https://login.microsoftonline.com/{self.tenant_id}"
    
    def get_token_endpoint(self) -> str:
        """Get Azure AD token endpoint"""
        return f"{self.base_url}/oauth2/v2.0/token"
    
    def get_jwks_uri(self) -> str:
        """Get Azure AD JWKS URI"""
        return f"{self.base_url}/discovery/v2.0/keys"
    
    def _get_expected_issuer(self) -> str:
        """Get expected token issuer for Azure AD"""
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
    
    async def get_token(self, tool_id: str, permissions: List[str]) -> str:
        """
        Get an OAuth token from Azure AD for a tool
        
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
            
            # Add scope - Azure AD requires specific format
            if permissions:
                # Azure AD scopes should be in format: https://graph.microsoft.com/.default
                # or custom app scopes like api://app-id/scope
                scopes = []
                for perm in permissions:
                    if not perm.startswith("https://") and not perm.startswith("api://"):
                        # Assume it's a custom scope for this app
                        scopes.append(f"api://{self.config.client_id}/{perm}")
                    else:
                        scopes.append(perm)
                data["scope"] = " ".join(scopes)
            elif self.config.scopes:
                data["scope"] = " ".join(self.config.scopes)
            else:
                # Default to Microsoft Graph
                data["scope"] = "https://graph.microsoft.com/.default"
            
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
                    f"Azure AD token request failed: {error_msg}",
                    provider=self.name,
                    oauth_error=error_data.get("error"),
                    status_code=response.status_code
                )
            
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                raise OAuthError("No access token in Azure AD response", provider=self.name)
            
            logger.info(f"Successfully obtained Azure AD token for tool {tool_id}")
            return access_token
            
        except httpx.RequestError as e:
            raise OAuthError(f"Azure AD request failed: {e}", provider=self.name)
        except Exception as e:
            if isinstance(e, OAuthError):
                raise
            raise OAuthError(f"Unexpected error getting Azure AD token: {e}", provider=self.name)
    
    async def validate_token(self, token: str, expected_claims: Dict[str, Any]) -> VerificationResult:
        """
        Validate an Azure AD JWT token
        
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
                # Azure AD uses 'scp' claim for scopes in v2.0 tokens
                token_scopes = decoded.get("scp", "")
                if isinstance(token_scopes, str):
                    token_scopes = token_scopes.split()
                elif isinstance(token_scopes, list):
                    pass  # Already a list
                else:
                    token_scopes = []
                
                token_scopes_set = set(token_scopes)
                required_scopes = set(required_permissions)
                
                missing_scopes = required_scopes - token_scopes_set
                if missing_scopes:
                    return VerificationResult(
                        valid=False,
                        provider=self.name,
                        error=f"Missing required scopes: {', '.join(missing_scopes)}"
                    )
            
            # Validate application ID (client ID)
            token_appid = decoded.get("appid") or decoded.get("azp")
            if token_appid and token_appid != self.config.client_id:
                return VerificationResult(
                    valid=False,
                    provider=self.name,
                    error=f"Token app_id mismatch: expected {self.config.client_id}, got {token_appid}"
                )
            
            # Validate tenant ID
            token_tid = decoded.get("tid")
            if token_tid and token_tid != self.tenant_id:
                return VerificationResult(
                    valid=False,
                    provider=self.name,
                    error=f"Token tenant_id mismatch: expected {self.tenant_id}, got {token_tid}"
                )
            
            return VerificationResult(
                valid=True,
                provider=self.name,
                details={
                    "issuer": decoded.get("iss"),
                    "subject": decoded.get("sub"),
                    "application_id": decoded.get("appid"),
                    "tenant_id": decoded.get("tid"),
                    "scopes": decoded.get("scp", "").split() if isinstance(decoded.get("scp"), str) else decoded.get("scp", []),
                    "expires_at": decoded.get("exp"),
                    "issued_at": decoded.get("iat"),
                    "tool_id": decoded.get("tool_id"),
                    "tool_version": decoded.get("tool_version"),
                    "object_id": decoded.get("oid"),  # Azure AD object ID
                    "version": decoded.get("ver")  # Token version
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
    
    async def get_tenant_info(self) -> Dict[str, Any]:
        """
        Get Azure AD tenant information
        
        Returns:
            Tenant information dictionary
        """
        try:
            response = await self.http_client.get(
                f"{self.base_url}/v2.0/.well-known/openid_configuration"
            )
            
            if response.status_code != 200:
                raise OAuthError(f"Azure AD tenant info request failed: HTTP {response.status_code}", provider=self.name)
            
            return response.json()
            
        except httpx.RequestError as e:
            raise OAuthError(f"Azure AD tenant info request failed: {e}", provider=self.name)
    
    async def revoke_token(self, token: str) -> bool:
        """
        Revoke an Azure AD token (Note: Azure AD doesn't have a standard revocation endpoint)
        
        Args:
            token: Token to revoke
            
        Returns:
            True if revocation was successful (always returns False for Azure AD)
        """
        # Azure AD doesn't have a standard token revocation endpoint
        # Tokens expire naturally based on their lifetime
        logger.warning("Azure AD does not support token revocation - tokens expire naturally")
        return False
    
    async def get_application_info(self, token: str) -> Dict[str, Any]:
        """
        Get application information using Microsoft Graph API
        
        Args:
            token: Access token with appropriate permissions
            
        Returns:
            Application information dictionary
        """
        try:
            response = await self.http_client.get(
                f"https://graph.microsoft.com/v1.0/applications/{self.config.client_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code != 200:
                raise OAuthError(f"Azure AD application info request failed: HTTP {response.status_code}", provider=self.name)
            
            return response.json()
            
        except httpx.RequestError as e:
            raise OAuthError(f"Azure AD application info request failed: {e}", provider=self.name)