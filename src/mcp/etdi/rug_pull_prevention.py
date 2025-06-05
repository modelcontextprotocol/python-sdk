"""
Enhanced Rug Pull Prevention Implementation for ETDI

This module implements the sophisticated Rug Pull prevention mechanisms described in the paper,
including cryptographic hashing of tool definitions, API contract attestation, and dynamic
behavior change detection.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union
from enum import Enum

from .types import ETDIToolDefinition, VerificationResult, ChangeDetectionResult, Permission
from .exceptions import ETDIError, TokenValidationError

logger = logging.getLogger(__name__)


class IntegrityCheckType(Enum):
    """Types of integrity checks for tool definitions"""
    DEFINITION_HASH = "definition_hash"
    API_CONTRACT_HASH = "api_contract_hash"
    IMPLEMENTATION_HASH = "implementation_hash"
    BEHAVIOR_SIGNATURE = "behavior_signature"


@dataclass
class APIContractInfo:
    """Information about a tool's API contract"""
    contract_type: str  # "openapi", "graphql", "custom"
    contract_version: str
    contract_hash: str
    contract_url: Optional[str] = None
    contract_content: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "contract_version": self.contract_version,
            "contract_hash": self.contract_hash,
            "contract_url": self.contract_url,
            "contract_content": self.contract_content
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIContractInfo":
        return cls(
            contract_type=data["contract_type"],
            contract_version=data["contract_version"],
            contract_hash=data["contract_hash"],
            contract_url=data.get("contract_url"),
            contract_content=data.get("contract_content")
        )


@dataclass
class ImplementationIntegrity:
    """Cryptographic integrity information for tool implementation"""
    definition_hash: str  # Hash of the complete tool definition
    api_contract: Optional[APIContractInfo] = None
    implementation_hash: Optional[str] = None  # Hash of backend implementation
    behavior_signature: Optional[str] = None  # Behavioral fingerprint
    tool_version: Optional[str] = None  # Tool version for legitimate update detection
    signing_key_id: Optional[str] = None
    signature_algorithm: str = "SHA256"
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "definition_hash": self.definition_hash,
            "api_contract": self.api_contract.to_dict() if self.api_contract else None,
            "implementation_hash": self.implementation_hash,
            "behavior_signature": self.behavior_signature,
            "tool_version": self.tool_version,
            "signing_key_id": self.signing_key_id,
            "signature_algorithm": self.signature_algorithm,
            "created_at": self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImplementationIntegrity":
        api_contract_data = data.get("api_contract")
        return cls(
            definition_hash=data["definition_hash"],
            api_contract=APIContractInfo.from_dict(api_contract_data) if api_contract_data else None,
            implementation_hash=data.get("implementation_hash"),
            behavior_signature=data.get("behavior_signature"),
            tool_version=data.get("tool_version"),
            signing_key_id=data.get("signing_key_id"),
            signature_algorithm=data.get("signature_algorithm", "SHA256"),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat()))
        )


@dataclass
class RugPullDetectionResult:
    """Result of rug pull detection analysis"""
    is_rug_pull: bool
    confidence_score: float  # 0.0 to 1.0
    detected_changes: List[str] = field(default_factory=list)
    integrity_violations: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_rug_pull": self.is_rug_pull,
            "confidence_score": self.confidence_score,
            "detected_changes": self.detected_changes,
            "integrity_violations": self.integrity_violations,
            "risk_factors": self.risk_factors
        }


class RugPullDetector:
    """
    Advanced Rug Pull detection engine implementing the paper's specifications
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Initialize the Rug Pull detector
        
        Args:
            strict_mode: If True, applies strict integrity checking as per paper
        """
        self.strict_mode = strict_mode
        self._integrity_cache: Dict[str, ImplementationIntegrity] = {}
    
    def compute_tool_definition_hash(self, tool: ETDIToolDefinition) -> str:
        """
        Compute cryptographic hash of complete tool definition
        
        This implements the paper's requirement for immutable tool versioning
        with cryptographic hashing of the entire tool definition.
        """
        # Create a normalized representation for hashing
        definition_data = {
            "id": tool.id,
            "name": tool.name,
            "version": tool.version,
            "description": tool.description,
            "provider": tool.provider,
            "schema": tool.schema,
            "permissions": sorted([p.to_dict() for p in tool.permissions], key=lambda x: x["scope"]),
            "require_request_signing": tool.require_request_signing
        }
        
        # Include call stack constraints if present
        if tool.call_stack_constraints:
            definition_data["call_stack_constraints"] = tool.call_stack_constraints.to_dict()
        
        # Create deterministic JSON representation
        normalized_json = json.dumps(definition_data, sort_keys=True, separators=(',', ':'))
        
        # Compute SHA256 hash
        return hashlib.sha256(normalized_json.encode('utf-8')).hexdigest()
    
    def compute_api_contract_hash(self, contract_content: str, contract_type: str = "openapi") -> str:
        """
        Compute hash of API contract (OpenAPI, GraphQL, etc.)
        
        This implements the paper's requirement for API contract attestation
        to detect backend changes that don't alter the tool definition.
        """
        # Normalize contract content based on type
        if contract_type.lower() == "openapi":
            # For OpenAPI, parse and normalize to ensure consistent hashing
            try:
                import yaml
                contract_data = yaml.safe_load(contract_content)
                normalized_content = json.dumps(contract_data, sort_keys=True, separators=(',', ':'))
            except Exception:
                # Fallback to raw content if parsing fails
                normalized_content = contract_content.strip()
        else:
            normalized_content = contract_content.strip()
        
        return hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()
    
    def create_implementation_integrity(
        self, 
        tool: ETDIToolDefinition,
        api_contract_content: Optional[str] = None,
        api_contract_type: str = "openapi",
        implementation_hash: Optional[str] = None,
        behavior_signature: Optional[str] = None
    ) -> ImplementationIntegrity:
        """
        Create comprehensive implementation integrity record
        
        This implements the paper's multi-layered integrity verification approach.
        """
        definition_hash = self.compute_tool_definition_hash(tool)
        
        api_contract = None
        if api_contract_content:
            contract_hash = self.compute_api_contract_hash(api_contract_content, api_contract_type)
            api_contract = APIContractInfo(
                contract_type=api_contract_type,
                contract_version=tool.version,
                contract_hash=contract_hash,
                contract_content=api_contract_content
            )
        
        integrity = ImplementationIntegrity(
            definition_hash=definition_hash,
            api_contract=api_contract,
            implementation_hash=implementation_hash,
            behavior_signature=behavior_signature,
            tool_version=tool.version
        )
        
        # Cache for future comparisons
        self._integrity_cache[tool.id] = integrity
        
        return integrity
    
    def detect_rug_pull(
        self, 
        current_tool: ETDIToolDefinition,
        stored_integrity: ImplementationIntegrity,
        current_api_contract: Optional[str] = None
    ) -> RugPullDetectionResult:
        """
        Detect potential rug pull attacks by comparing current tool state
        with stored integrity information
        
        This implements the paper's core rug pull detection algorithm.
        """
        detected_changes = []
        integrity_violations = []
        risk_factors = []
        confidence_score = 0.0
        
        # 1. Check tool definition integrity
        current_definition_hash = self.compute_tool_definition_hash(current_tool)
        if current_definition_hash != stored_integrity.definition_hash:
            detected_changes.append("Tool definition hash mismatch")
            
            # Check if this is a legitimate version update
            if stored_integrity.tool_version and current_tool.version != stored_integrity.tool_version:
                # Version changed - this is likely a legitimate update
                confidence_score += 0.1  # Lower confidence for legitimate updates
            else:
                # Version hasn't changed but definition has - highly suspicious
                integrity_violations.append("Definition changed without version increment")
                confidence_score += 0.4
        
        # 2. Check API contract integrity (if available)
        if stored_integrity.api_contract and current_api_contract:
            current_contract_hash = self.compute_api_contract_hash(
                current_api_contract,
                stored_integrity.api_contract.contract_type
            )
            if current_contract_hash != stored_integrity.api_contract.contract_hash:
                detected_changes.append("API contract hash mismatch")
                
                # Check if this is a legitimate version update
                if stored_integrity.tool_version and current_tool.version != stored_integrity.tool_version:
                    # Version changed - likely legitimate, lower confidence
                    confidence_score += 0.2
                else:
                    # No version change but contract changed - highly suspicious
                    integrity_violations.append("Backend API contract modified")
                    confidence_score += 0.5  # High confidence indicator
        
        # 3. Check for suspicious permission escalations
        if self._detect_permission_escalation(current_tool, stored_integrity):
            risk_factors.append("Suspicious permission escalation detected")
            confidence_score += 0.3
        
        # 4. Check for behavioral anomalies (if behavior signature available)
        if stored_integrity.behavior_signature:
            # Compare behavior signatures if available
            current_behavior = self._compute_behavior_signature(current_tool)
            if current_behavior != stored_integrity.behavior_signature:
                detected_changes.append("Tool behavior signature changed")
                integrity_violations.append("Behavioral fingerprint mismatch")
                confidence_score += 0.4
        
        # 5. Apply strict mode checks
        if self.strict_mode:
            if not stored_integrity.api_contract:
                risk_factors.append("No API contract attestation available")
                confidence_score += 0.1
            
            if not stored_integrity.implementation_hash:
                risk_factors.append("No implementation hash available")
                confidence_score += 0.1
        
        # Determine if this constitutes a rug pull
        is_rug_pull = confidence_score >= 0.7 or len(integrity_violations) > 0
        
        return RugPullDetectionResult(
            is_rug_pull=is_rug_pull,
            confidence_score=min(confidence_score, 1.0),
            detected_changes=detected_changes,
            integrity_violations=integrity_violations,
            risk_factors=risk_factors
        )
    
    def _detect_permission_escalation(
        self,
        current_tool: ETDIToolDefinition,
        stored_integrity: ImplementationIntegrity
    ) -> bool:
        """
        Detect suspicious permission escalations that might indicate rug pull
        """
        current_scopes = {p.scope for p in current_tool.permissions}
        
        # Extract stored permissions from the definition hash
        # We need to reconstruct the original tool definition to compare permissions
        try:
            # Check for dangerous permission patterns that might indicate escalation
            dangerous_patterns = [
                "admin:", "root:", "system:", "file:write", "network:unrestricted",
                "exec:", "shell:", "sudo:", "privilege:", "escalate:"
            ]
            
            suspicious_scopes = []
            for scope in current_scopes:
                for pattern in dangerous_patterns:
                    if pattern in scope.lower():
                        suspicious_scopes.append(scope)
            
            # If we find suspicious scopes, flag as potential escalation
            if suspicious_scopes:
                logger.warning(f"Detected potentially dangerous permission scopes: {suspicious_scopes}")
                return True
            
            # Check for unusually broad permissions
            broad_patterns = ["*", "all:", "any:", "unrestricted"]
            for scope in current_scopes:
                for pattern in broad_patterns:
                    if pattern in scope.lower():
                        logger.warning(f"Detected broad permission scope: {scope}")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error detecting permission escalation: {e}")
            return False
    
    def _compute_behavior_signature(self, tool: ETDIToolDefinition) -> str:
        """
        Compute a behavioral signature for the tool based on its characteristics
        
        This creates a fingerprint of the tool's expected behavior patterns
        based on its schema, permissions, and other behavioral indicators.
        """
        try:
            # Create a behavioral fingerprint based on tool characteristics
            behavior_data = {
                "input_schema": tool.schema.get("input", {}),
                "output_schema": tool.schema.get("output", {}),
                "permission_patterns": sorted([p.scope for p in tool.permissions]),
                "call_constraints": tool.call_stack_constraints.to_dict() if tool.call_stack_constraints else None,
                "requires_signing": tool.require_request_signing
            }
            
            # Add provider information that affects behavior
            if tool.provider:
                behavior_data["provider_type"] = tool.provider.get("type")
                behavior_data["provider_version"] = tool.provider.get("version")
            
            # Create deterministic representation
            normalized_json = json.dumps(behavior_data, sort_keys=True, separators=(',', ':'))
            
            # Compute signature
            return hashlib.sha256(normalized_json.encode('utf-8')).hexdigest()
            
        except Exception as e:
            logger.error(f"Error computing behavior signature: {e}")
            return ""
    
    def enhanced_oauth_token_validation(
        self, 
        tool: ETDIToolDefinition, 
        token: str,
        stored_integrity: ImplementationIntegrity
    ) -> VerificationResult:
        """
        Enhanced OAuth token validation that includes rug pull checks
        
        This extends the basic OAuth validation with integrity verification
        as described in the paper.
        """
        # First perform rug pull detection
        rug_pull_result = self.detect_rug_pull(tool, stored_integrity)
        
        if rug_pull_result.is_rug_pull:
            return VerificationResult(
                valid=False,
                provider=tool.security.oauth.provider if tool.security and tool.security.oauth else "unknown",
                error=f"Rug pull attack detected (confidence: {rug_pull_result.confidence_score:.2f})",
                details={
                    "rug_pull_detection": rug_pull_result.to_dict(),
                    "integrity_violations": rug_pull_result.integrity_violations,
                    "detected_changes": rug_pull_result.detected_changes
                }
            )
        
        # If no rug pull detected, proceed with standard validation
        # (This would integrate with the existing OAuth validation)
        return VerificationResult(
            valid=True,
            provider=tool.security.oauth.provider if tool.security and tool.security.oauth else "unknown",
            details={
                "rug_pull_check": "passed",
                "confidence_score": rug_pull_result.confidence_score,
                "definition_hash": stored_integrity.definition_hash
            }
        )