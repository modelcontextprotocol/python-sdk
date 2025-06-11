"""
ETDI tool verification engine for client-side security checks with Rug Pull prevention
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
import hashlib
import json

from ..types import (
    ETDIToolDefinition,
    VerificationResult,
    InvocationCheck,
    ChangeDetectionResult,
    VerificationStatus,
    Permission
)
from ..exceptions import ETDIError, TokenValidationError, ProviderError
from ..oauth import OAuthManager
from ..rug_pull_prevention import RugPullDetector, ImplementationIntegrity
from ..oauth.enhanced_provider import create_enhanced_provider

logger = logging.getLogger(__name__)


class ETDIVerifier:
    """
    Tool verification engine that validates OAuth tokens and detects changes with Rug Pull prevention
    """
    
    def __init__(self, oauth_manager: OAuthManager, cache_ttl: int = 300, enable_rug_pull_detection: bool = True):
        """
        Initialize the verifier
        
        Args:
            oauth_manager: OAuth manager for token validation
            cache_ttl: Cache TTL in seconds (default: 5 minutes)
            enable_rug_pull_detection: Enable advanced rug pull detection
        """
        self.oauth_manager = oauth_manager
        self.cache_ttl = cache_ttl
        self.enable_rug_pull_detection = enable_rug_pull_detection
        self._verification_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
        
        # Initialize rug pull detector if enabled
        if self.enable_rug_pull_detection:
            self.rug_pull_detector = RugPullDetector(strict_mode=True)
            self._integrity_store: Dict[str, ImplementationIntegrity] = {}
        else:
            self.rug_pull_detector = None
            self._integrity_store = {}
    
    async def verify_tool(self, tool: ETDIToolDefinition) -> VerificationResult:
        """
        Verify a tool's OAuth token and security information
        
        Args:
            tool: Tool definition to verify
            
        Returns:
            VerificationResult with verification details
        """
        try:
            # Check if tool has security information
            if not tool.security or not tool.security.oauth:
                return VerificationResult(
                    valid=False,
                    provider="none",
                    error="Tool has no OAuth security information"
                )
            
            oauth_info = tool.security.oauth
            
            # Check cache first
            cache_key = self._get_cache_key(tool.id, oauth_info.token)
            cached_result = await self._get_cached_result(cache_key)
            if cached_result:
                logger.debug(f"Using cached verification result for tool {tool.id}")
                return cached_result
            
            # Verify with OAuth provider
            expected_claims = {
                "toolId": tool.id,
                "toolVersion": tool.version,
                "requiredPermissions": tool.get_permission_scopes()
            }
            
            result = await self.oauth_manager.validate_token(
                oauth_info.provider,
                oauth_info.token,
                expected_claims
            )
            
            # Update tool verification status
            if result.valid:
                tool.verification_status = VerificationStatus.VERIFIED
                logger.info(f"Tool {tool.id} verification successful")
            else:
                tool.verification_status = VerificationStatus.TOKEN_INVALID
                logger.warning(f"Tool {tool.id} verification failed: {result.error}")
            
            # Cache the result
            await self._cache_result(cache_key, result)
            
            return result
            
        except ProviderError as e:
            tool.verification_status = VerificationStatus.PROVIDER_UNKNOWN
            return VerificationResult(
                valid=False,
                provider=oauth_info.provider if tool.security and tool.security.oauth else "unknown",
                error=f"Provider error: {e.message}"
            )
        except Exception as e:
            tool.verification_status = VerificationStatus.UNVERIFIED
            logger.error(f"Unexpected error verifying tool {tool.id}: {e}")
            return VerificationResult(
                valid=False,
                provider=oauth_info.provider if tool.security and tool.security.oauth else "unknown",
                error=f"Verification error: {str(e)}"
            )
    
    async def verify_tool_with_rug_pull_detection(
        self,
        tool: ETDIToolDefinition,
        api_contract: Optional[str] = None,
        implementation_hash: Optional[str] = None
    ) -> VerificationResult:
        """
        Verify a tool with comprehensive rug pull detection
        
        This implements the paper's enhanced verification that includes
        integrity verification and rug pull detection.
        
        Args:
            tool: Tool definition to verify
            api_contract: Optional API contract content for integrity checking
            implementation_hash: Optional implementation hash
            
        Returns:
            VerificationResult with enhanced verification details
        """
        if not self.enable_rug_pull_detection or not self.rug_pull_detector:
            # Fall back to standard verification
            return await self.verify_tool(tool)
        
        try:
            # First perform standard OAuth verification
            standard_result = await self.verify_tool(tool)
            
            if not standard_result.valid:
                return standard_result
            
            # Check if we have stored integrity information
            stored_integrity = self._integrity_store.get(tool.id)
            
            if not stored_integrity:
                # First time seeing this tool - create integrity record
                stored_integrity = self.rug_pull_detector.create_implementation_integrity(
                    tool,
                    api_contract_content=api_contract,
                    implementation_hash=implementation_hash
                )
                self._integrity_store[tool.id] = stored_integrity
                
                # Return successful verification for first-time tools
                return VerificationResult(
                    valid=True,
                    provider=standard_result.provider,
                    details={
                        **standard_result.details,
                        "rug_pull_check": "first_time_tool",
                        "integrity_created": True,
                        "definition_hash": stored_integrity.definition_hash
                    }
                )
            
            # Perform rug pull detection
            rug_pull_result = self.rug_pull_detector.detect_rug_pull(
                tool, stored_integrity, api_contract
            )
            
            if rug_pull_result.is_rug_pull:
                return VerificationResult(
                    valid=False,
                    provider=standard_result.provider,
                    error=f"Rug pull attack detected (confidence: {rug_pull_result.confidence_score:.2f})",
                    details={
                        "rug_pull_detection": rug_pull_result.to_dict(),
                        "integrity_violations": rug_pull_result.integrity_violations,
                        "detected_changes": rug_pull_result.detected_changes
                    }
                )
            
            # All checks passed
            return VerificationResult(
                valid=True,
                provider=standard_result.provider,
                details={
                    **(standard_result.details or {}),
                    "rug_pull_check": "passed",
                    "confidence_score": rug_pull_result.confidence_score,
                    "definition_hash": stored_integrity.definition_hash
                }
            )
            
        except Exception as e:
            logger.error(f"Error during enhanced verification for tool {tool.id}: {e}")
            return VerificationResult(
                valid=False,
                provider=tool.security.oauth.provider if tool.security and tool.security.oauth else "unknown",
                error=f"Enhanced verification error: {str(e)}"
            )
    
    async def check_tool_before_invocation(
        self, 
        tool: ETDIToolDefinition,
        stored_approval: Optional[Dict[str, Any]] = None
    ) -> InvocationCheck:
        """
        Check if a tool can be invoked safely
        
        Args:
            tool: Tool definition to check
            stored_approval: Previously stored approval record
            
        Returns:
            InvocationCheck with safety assessment
        """
        try:
            # First verify the tool's current state
            verification_result = await self.verify_tool(tool)
            
            if not verification_result.valid:
                return InvocationCheck(
                    can_proceed=False,
                    requires_reapproval=False,
                    reason="INVALID_TOKEN",
                    changes_detected=[f"Token validation failed: {verification_result.error}"]
                )
            
            # If no stored approval, require approval
            if not stored_approval:
                return InvocationCheck(
                    can_proceed=False,
                    requires_reapproval=True,
                    reason="NOT_APPROVED",
                    changes_detected=["Tool has not been approved by user"]
                )
            
            # Check for changes since approval
            changes = await self._detect_changes(tool, stored_approval)
            
            if changes.has_changes:
                change_descriptions = []
                if changes.version_changed:
                    change_descriptions.append("Tool version changed")
                if changes.permissions_changed:
                    change_descriptions.append("Tool permissions changed")
                if changes.provider_changed:
                    change_descriptions.append("OAuth provider changed")
                
                return InvocationCheck(
                    can_proceed=False,
                    requires_reapproval=True,
                    reason="CHANGES_DETECTED",
                    changes_detected=change_descriptions
                )
            
            # All checks passed
            return InvocationCheck(
                can_proceed=True,
                requires_reapproval=False
            )
            
        except Exception as e:
            logger.error(f"Error checking tool {tool.id} before invocation: {e}")
            return InvocationCheck(
                can_proceed=False,
                requires_reapproval=False,
                reason="CHECK_ERROR",
                changes_detected=[f"Error during safety check: {str(e)}"]
            )
    
    async def _detect_changes(
        self, 
        current_tool: ETDIToolDefinition, 
        stored_approval: Dict[str, Any]
    ) -> ChangeDetectionResult:
        """
        Detect changes between current tool and stored approval
        
        Args:
            current_tool: Current tool definition
            stored_approval: Previously stored approval data
            
        Returns:
            ChangeDetectionResult with detected changes
        """
        changes = ChangeDetectionResult(has_changes=False)
        
        # Check version changes
        approved_version = stored_approval.get("approved_version")
        if approved_version and current_tool.version != approved_version:
            changes.has_changes = True
            changes.version_changed = True
        
        # Check provider changes
        approved_provider = stored_approval.get("provider_id")
        current_provider = current_tool.security.oauth.provider if current_tool.security and current_tool.security.oauth else None
        if approved_provider and current_provider != approved_provider:
            changes.has_changes = True
            changes.provider_changed = True
        
        # Check permission changes
        approved_permissions = stored_approval.get("permissions", [])
        current_permissions = current_tool.permissions
        
        if self._permissions_changed(approved_permissions, current_permissions):
            changes.has_changes = True
            changes.permissions_changed = True
            
            # Identify specific permission changes
            approved_scopes = {p.get("scope") if isinstance(p, dict) else p.scope for p in approved_permissions}
            current_scopes = {p.scope for p in current_permissions}
            
            new_scopes = current_scopes - approved_scopes
            removed_scopes = approved_scopes - current_scopes
            
            # Find new permissions
            changes.new_permissions = [p for p in current_permissions if p.scope in new_scopes]
            
            # Find removed permissions (reconstruct from stored data)
            for perm_data in approved_permissions:
                if isinstance(perm_data, dict):
                    scope = perm_data.get("scope")
                    if scope in removed_scopes:
                        changes.removed_permissions.append(Permission.from_dict(perm_data))
                elif hasattr(perm_data, 'scope') and perm_data.scope in removed_scopes:
                    changes.removed_permissions.append(perm_data)
        
        return changes
    
    def _permissions_changed(self, approved_permissions: List[Any], current_permissions: List[Permission]) -> bool:
        """Check if permissions have changed"""
        # Convert approved permissions to comparable format
        approved_scopes = set()
        for perm in approved_permissions:
            if isinstance(perm, dict):
                approved_scopes.add(perm.get("scope"))
            elif hasattr(perm, 'scope'):
                approved_scopes.add(perm.scope)
            else:
                approved_scopes.add(str(perm))
        
        current_scopes = {p.scope for p in current_permissions}
        
        return approved_scopes != current_scopes
    
    def _get_cache_key(self, tool_id: str, token: str) -> str:
        """Generate cache key for verification result"""
        # Use hash of token to avoid storing full token in cache key
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"{tool_id}:{token_hash}"
    
    async def _get_cached_result(self, cache_key: str) -> Optional[VerificationResult]:
        """Get cached verification result if still valid"""
        async with self._cache_lock:
            cached = self._verification_cache.get(cache_key)
            if cached and cached["expires_at"] > datetime.now():
                return cached["result"]
            elif cached:
                # Remove expired entry
                del self._verification_cache[cache_key]
        return None
    
    async def _cache_result(self, cache_key: str, result: VerificationResult) -> None:
        """Cache verification result"""
        async with self._cache_lock:
            self._verification_cache[cache_key] = {
                "result": result,
                "expires_at": datetime.now() + timedelta(seconds=self.cache_ttl)
            }
    
    def clear_cache(self) -> None:
        """Clear the verification cache"""
        self._verification_cache.clear()
    
    async def batch_verify_tools(self, tools: List[ETDIToolDefinition]) -> Dict[str, VerificationResult]:
        """
        Verify multiple tools in parallel
        
        Args:
            tools: List of tools to verify
            
        Returns:
            Dictionary mapping tool IDs to verification results
        """
        tasks = []
        for tool in tools:
            task = asyncio.create_task(self.verify_tool(tool))
            tasks.append((tool.id, task))
        
        results = {}
        for tool_id, task in tasks:
            try:
                result = await task
                results[tool_id] = result
            except Exception as e:
                logger.error(f"Error verifying tool {tool_id}: {e}")
                results[tool_id] = VerificationResult(
                    valid=False,
                    provider="unknown",
                    error=f"Verification error: {str(e)}"
                )
        
        return results
    
    async def get_verification_stats(self) -> Dict[str, Any]:
        """
        Get verification statistics
        
        Returns:
            Dictionary with verification statistics
        """
        async with self._cache_lock:
            cache_size = len(self._verification_cache)
            expired_entries = sum(
                1 for entry in self._verification_cache.values()
                if entry["expires_at"] <= datetime.now()
            )
        
        return {
            "cache_size": cache_size,
            "expired_entries": expired_entries,
            "cache_ttl_seconds": self.cache_ttl,
            "available_providers": self.oauth_manager.list_providers()
        }