"""
Enhanced OAuth Provider with Rug Pull Prevention

This module implements the OAuth enhancements described in the paper, including
proper tool_id embedding, API contract attestation, and rug pull detection.
"""

import json
import logging
from typing import Any, Dict, List, Optional
import jwt
from datetime import datetime, timedelta

from .auth0 import Auth0Provider
from .okta import OktaProvider
from .azure import AzureADProvider
from .custom import CustomOAuthProvider
from ..types import OAuthConfig, VerificationResult, ETDIToolDefinition
from ..exceptions import OAuthError, TokenValidationError
from ..rug_pull_prevention import RugPullDetector, ImplementationIntegrity

logger = logging.getLogger(__name__)


class EnhancedAuth0Provider(Auth0Provider):
    """
    Enhanced Auth0 provider with rug pull prevention capabilities
    """
    
    def __init__(self, config: OAuthConfig, rug_pull_detector: Optional[RugPullDetector] = None):
        super().__init__(config)
        self.rug_pull_detector = rug_pull_detector or RugPullDetector(strict_mode=True)
        self._integrity_store: Dict[str, ImplementationIntegrity] = {}
    
    async def get_token_with_integrity(
        self, 
        tool_id: str, 
        permissions: List[str],
        tool_definition: ETDIToolDefinition,
        api_contract: Optional[str] = None,
        implementation_hash: Optional[str] = None
    ) -> str:
        """
        Get OAuth token with embedded tool integrity information
        
        This implements the paper's requirement for embedding tool_id and
        integrity information in OAuth tokens.
        """
        # Create implementation integrity record
        integrity = self.rug_pull_detector.create_implementation_integrity(
            tool_definition, 
            api_contract_content=api_contract,
            implementation_hash=implementation_hash
        )
        
        # Store integrity information for future verification
        self._integrity_store[tool_id] = integrity
        
        # Enhance permissions with tool-specific scopes as described in the paper
        enhanced_permissions = permissions.copy()
        enhanced_permissions.extend([
            f"tool:{tool_id}:execute",
            f"tool:{tool_id}:version:{tool_definition.version}",
            f"tool:{tool_id}:integrity:{integrity.definition_hash[:16]}"  # Short hash for scope
        ])
        
        # Add API contract scope if available
        if integrity.api_contract:
            enhanced_permissions.append(
                f"tool:{tool_id}:contract:{integrity.api_contract.contract_hash[:16]}"
            )
        
        # Add implementation hash scope if available
        if integrity.implementation_hash:
            enhanced_permissions.append(
                f"tool:{tool_id}:impl:{integrity.implementation_hash[:16]}"
            )
        
        try:
            # Build enhanced request data
            data = {
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": " ".join(enhanced_permissions),
                # Custom claims for tool integrity
                "tool_id": tool_id,
                "tool_definition_hash": integrity.definition_hash,
                "tool_version": tool_definition.version,
                "integrity_created_at": integrity.created_at.isoformat()
            }
            
            # Add audience if specified
            if self.config.audience:
                data["audience"] = self.config.audience
            
            # Add API contract hash if available
            if integrity.api_contract:
                data["api_contract_hash"] = integrity.api_contract.contract_hash
                data["api_contract_type"] = integrity.api_contract.contract_type
            
            # Add implementation hash if available
            if integrity.implementation_hash:
                data["implementation_hash"] = integrity.implementation_hash
            
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
                    f"Enhanced Auth0 token request failed: {error_msg}",
                    provider=self.name,
                    oauth_error=error_data.get("error"),
                    status_code=response.status_code
                )
            
            token_response = response.json()
            access_token = token_response.get("access_token")
            
            if not access_token:
                raise OAuthError("No access token in Auth0 response", provider=self.name)
            
            logger.info(f"Successfully obtained enhanced Auth0 token for tool {tool_id} with integrity verification")
            return access_token
            
        except Exception as e:
            if isinstance(e, OAuthError):
                raise
            raise OAuthError(f"Unexpected error getting enhanced Auth0 token: {e}", provider=self.name)
    
    async def validate_token_with_rug_pull_check(
        self, 
        token: str, 
        tool: ETDIToolDefinition,
        expected_claims: Dict[str, Any],
        current_api_contract: Optional[str] = None
    ) -> VerificationResult:
        """
        Validate OAuth token with comprehensive rug pull detection
        """
        try:
            # First validate basic token structure and signature
            basic_result = await self.validate_token(token, expected_claims)
            
            if not basic_result.valid:
                return basic_result
            
            # Get stored integrity information
            stored_integrity = self._integrity_store.get(tool.id)
            if not stored_integrity:
                # Try to reconstruct from token claims
                stored_integrity = self._extract_integrity_from_token(token, tool)
                if not stored_integrity:
                    return VerificationResult(
                        valid=False,
                        provider=self.name,
                        error="No stored integrity information for rug pull detection"
                    )
            
            # Perform rug pull detection
            return self.rug_pull_detector.enhanced_oauth_token_validation(
                tool, token, stored_integrity
            )
            
        except Exception as e:
            logger.error(f"Error during enhanced token validation: {e}")
            return VerificationResult(
                valid=False,
                provider=self.name,
                error=f"Enhanced validation error: {str(e)}"
            )
    
    def _extract_integrity_from_token(self, token: str, tool: ETDIToolDefinition) -> Optional[ImplementationIntegrity]:
        """
        Extract integrity information from token claims
        """
        try:
            # Decode token without verification to extract claims
            decoded = jwt.decode(token, options={"verify_signature": False})
            
            definition_hash = decoded.get("tool_definition_hash")
            if not definition_hash:
                return None
            
            # Reconstruct API contract info if present
            api_contract = None
            contract_hash = decoded.get("api_contract_hash")
            if contract_hash:
                from ..rug_pull_prevention import APIContractInfo
                api_contract = APIContractInfo(
                    contract_type=decoded.get("api_contract_type", "openapi"),
                    contract_version=tool.version,
                    contract_hash=contract_hash
                )
            
            # Create integrity record from token claims
            integrity = ImplementationIntegrity(
                definition_hash=definition_hash,
                api_contract=api_contract,
                implementation_hash=decoded.get("implementation_hash"),
                created_at=datetime.fromisoformat(decoded.get("integrity_created_at", datetime.now().isoformat()))
            )
            
            return integrity
            
        except Exception as e:
            logger.warning(f"Failed to extract integrity from token: {e}")
            return None
    
    def store_integrity_record(self, tool_id: str, integrity: ImplementationIntegrity) -> None:
        """Store integrity record for a tool"""
        self._integrity_store[tool_id] = integrity
    
    def get_integrity_record(self, tool_id: str) -> Optional[ImplementationIntegrity]:
        """Get stored integrity record for a tool"""
        return self._integrity_store.get(tool_id)


class EnhancedOktaProvider(OktaProvider):
    """
    Enhanced Okta provider with rug pull prevention capabilities
    """
    
    def __init__(self, config: OAuthConfig, rug_pull_detector: Optional[RugPullDetector] = None):
        super().__init__(config)
        self.rug_pull_detector = rug_pull_detector or RugPullDetector(strict_mode=True)
        self._integrity_store: Dict[str, ImplementationIntegrity] = {}
    
    async def get_token_with_integrity(
        self, 
        tool_id: str, 
        permissions: List[str],
        tool_definition: ETDIToolDefinition,
        api_contract: Optional[str] = None,
        implementation_hash: Optional[str] = None
    ) -> str:
        """Get OAuth token with embedded tool integrity information for Okta"""
        # Create implementation integrity record
        integrity = self.rug_pull_detector.create_implementation_integrity(
            tool_definition, 
            api_contract_content=api_contract,
            implementation_hash=implementation_hash
        )
        
        # Store integrity information
        self._integrity_store[tool_id] = integrity
        
        # Enhance permissions with tool-specific scopes
        enhanced_permissions = permissions.copy()
        enhanced_permissions.extend([
            f"tool:{tool_id}:execute",
            f"tool:{tool_id}:version:{tool_definition.version}",
            f"tool:{tool_id}:integrity:{integrity.definition_hash[:16]}"
        ])
        
        # Use the base Okta implementation with enhanced permissions
        return await super().get_token(tool_id, enhanced_permissions)
    
    async def validate_token_with_rug_pull_check(
        self, 
        token: str, 
        tool: ETDIToolDefinition,
        expected_claims: Dict[str, Any],
        current_api_contract: Optional[str] = None
    ) -> VerificationResult:
        """Validate OAuth token with rug pull detection for Okta"""
        basic_result = await self.validate_token(token, expected_claims)
        
        if not basic_result.valid:
            return basic_result
        
        stored_integrity = self._integrity_store.get(tool.id)
        if stored_integrity:
            return self.rug_pull_detector.enhanced_oauth_token_validation(
                tool, token, stored_integrity
            )
        
        return basic_result


class EnhancedAzureProvider(AzureADProvider):
    """
    Enhanced Azure provider with rug pull prevention capabilities
    """
    
    def __init__(self, config: OAuthConfig, rug_pull_detector: Optional[RugPullDetector] = None):
        super().__init__(config)
        self.rug_pull_detector = rug_pull_detector or RugPullDetector(strict_mode=True)
        self._integrity_store: Dict[str, ImplementationIntegrity] = {}
    
    async def get_token_with_integrity(
        self, 
        tool_id: str, 
        permissions: List[str],
        tool_definition: ETDIToolDefinition,
        api_contract: Optional[str] = None,
        implementation_hash: Optional[str] = None
    ) -> str:
        """Get OAuth token with embedded tool integrity information for Azure"""
        # Create implementation integrity record
        integrity = self.rug_pull_detector.create_implementation_integrity(
            tool_definition, 
            api_contract_content=api_contract,
            implementation_hash=implementation_hash
        )
        
        # Store integrity information
        self._integrity_store[tool_id] = integrity
        
        # Enhance permissions with tool-specific scopes
        enhanced_permissions = permissions.copy()
        enhanced_permissions.extend([
            f"tool:{tool_id}:execute",
            f"tool:{tool_id}:version:{tool_definition.version}",
            f"tool:{tool_id}:integrity:{integrity.definition_hash[:16]}"
        ])
        
        # Use the base Azure implementation with enhanced permissions
        return await super().get_token(tool_id, enhanced_permissions)
    
    async def validate_token_with_rug_pull_check(
        self, 
        token: str, 
        tool: ETDIToolDefinition,
        expected_claims: Dict[str, Any],
        current_api_contract: Optional[str] = None
    ) -> VerificationResult:
        """Validate OAuth token with rug pull detection for Azure"""
        basic_result = await self.validate_token(token, expected_claims)
        
        if not basic_result.valid:
            return basic_result
        
        stored_integrity = self._integrity_store.get(tool.id)
        if stored_integrity:
            return self.rug_pull_detector.enhanced_oauth_token_validation(
                tool, token, stored_integrity
            )
        
        return basic_result


def create_enhanced_provider(
    provider_type: str, 
    config: OAuthConfig, 
    rug_pull_detector: Optional[RugPullDetector] = None
) -> Any:
    """
    Factory function to create enhanced OAuth providers
    
    Args:
        provider_type: Type of provider ("auth0", "okta", "azure", "custom")
        config: OAuth configuration
        rug_pull_detector: Optional rug pull detector instance
        
    Returns:
        Enhanced OAuth provider instance
    """
    if provider_type.lower() == "auth0":
        return EnhancedAuth0Provider(config, rug_pull_detector)
    elif provider_type.lower() == "okta":
        return EnhancedOktaProvider(config, rug_pull_detector)
    elif provider_type.lower() == "azure":
        return EnhancedAzureProvider(config, rug_pull_detector)
    else:
        raise ValueError(f"Unsupported enhanced provider type: {provider_type}")