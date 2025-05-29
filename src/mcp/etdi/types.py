"""
Core data types for ETDI (Enhanced Tool Definition Interface)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json


class SecurityLevel(Enum):
    """Security levels for ETDI implementation"""
    BASIC = "basic"
    ENHANCED = "enhanced"
    STRICT = "strict"


class VerificationStatus(Enum):
    """Status of tool verification"""
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    TOKEN_INVALID = "token_invalid"
    PROVIDER_UNKNOWN = "provider_unknown"
    SIGNATURE_INVALID = "signature_invalid"
    EXPIRED = "expired"


@dataclass
class Permission:
    """Represents a permission required by a tool"""
    name: str
    description: str
    scope: str
    required: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "required": self.required
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Permission":
        return cls(
            name=data["name"],
            description=data["description"],
            scope=data["scope"],
            required=data.get("required", True)
        )


@dataclass
class OAuthInfo:
    """OAuth token information for a tool"""
    token: str
    provider: str
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "provider": self.provider,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthInfo":
        return cls(
            token=data["token"],
            provider=data["provider"],
            issued_at=datetime.fromisoformat(data["issued_at"]) if data.get("issued_at") else None,
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
        )


@dataclass
class SecurityInfo:
    """Security information for a tool definition"""
    oauth: Optional[OAuthInfo] = None
    signature: Optional[str] = None
    signature_algorithm: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "oauth": self.oauth.to_dict() if self.oauth else None,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityInfo":
        oauth_data = data.get("oauth")
        return cls(
            oauth=OAuthInfo.from_dict(oauth_data) if oauth_data else None,
            signature=data.get("signature"),
            signature_algorithm=data.get("signature_algorithm")
        )


@dataclass
class CallStackConstraints:
    """Call stack constraints for a tool"""
    max_depth: Optional[int] = None
    allowed_callers: Optional[List[str]] = None
    allowed_callees: Optional[List[str]] = None
    blocked_callers: Optional[List[str]] = None
    blocked_callees: Optional[List[str]] = None
    require_approval_for_chains: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "allowed_callers": self.allowed_callers,
            "allowed_callees": self.allowed_callees,
            "blocked_callers": self.blocked_callers,
            "blocked_callees": self.blocked_callees,
            "require_approval_for_chains": self.require_approval_for_chains
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallStackConstraints":
        return cls(
            max_depth=data.get("max_depth"),
            allowed_callers=data.get("allowed_callers"),
            allowed_callees=data.get("allowed_callees"),
            blocked_callers=data.get("blocked_callers"),
            blocked_callees=data.get("blocked_callees"),
            require_approval_for_chains=data.get("require_approval_for_chains", False)
        )


@dataclass
class ETDIToolDefinition:
    """Enhanced tool definition with security information"""
    id: str
    name: str
    version: str
    description: str
    provider: Dict[str, str]
    schema: Dict[str, Any]
    permissions: List[Permission] = field(default_factory=list)
    security: Optional[SecurityInfo] = None
    call_stack_constraints: Optional[CallStackConstraints] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    require_request_signing: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "provider": self.provider,
            "schema": self.schema,
            "permissions": [p.to_dict() for p in self.permissions],
            "security": self.security.to_dict() if self.security else None,
            "call_stack_constraints": self.call_stack_constraints.to_dict() if self.call_stack_constraints else None,
            "verification_status": self.verification_status.value,
            "require_request_signing": self.require_request_signing
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ETDIToolDefinition":
        permissions = [Permission.from_dict(p) for p in data.get("permissions", [])]
        security_data = data.get("security")
        constraints_data = data.get("call_stack_constraints")
        
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data["description"],
            provider=data["provider"],
            schema=data["schema"],
            permissions=permissions,
            security=SecurityInfo.from_dict(security_data) if security_data else None,
            call_stack_constraints=CallStackConstraints.from_dict(constraints_data) if constraints_data else None,
            verification_status=VerificationStatus(data.get("verification_status", "unverified")),
            require_request_signing=data.get("require_request_signing", False)
        )
    
    def get_permission_scopes(self) -> List[str]:
        """Get list of OAuth scopes for this tool's permissions"""
        return [p.scope for p in self.permissions if p.required]
    
    def has_permission(self, scope: str) -> bool:
        """Check if tool has a specific permission scope"""
        return any(p.scope == scope for p in self.permissions)


@dataclass
class ToolApprovalRecord:
    """Record of user approval for a tool"""
    tool_id: str
    provider_id: str
    approved_version: str
    permissions: List[Permission]
    approval_date: datetime
    expiry_date: Optional[datetime] = None
    definition_hash: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "provider_id": self.provider_id,
            "approved_version": self.approved_version,
            "permissions": [p.to_dict() for p in self.permissions],
            "approval_date": self.approval_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "definition_hash": self.definition_hash
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolApprovalRecord":
        permissions = [Permission.from_dict(p) for p in data["permissions"]]
        
        return cls(
            tool_id=data["tool_id"],
            provider_id=data["provider_id"],
            approved_version=data["approved_version"],
            permissions=permissions,
            approval_date=datetime.fromisoformat(data["approval_date"]),
            expiry_date=datetime.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
            definition_hash=data.get("definition_hash")
        )
    
    def is_expired(self) -> bool:
        """Check if approval has expired"""
        if self.expiry_date is None:
            return False
        return datetime.now() > self.expiry_date


@dataclass
class VerificationResult:
    """Result of tool verification"""
    valid: bool
    provider: str
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "provider": self.provider,
            "error": self.error,
            "details": self.details
        }


@dataclass
class InvocationCheck:
    """Result of pre-invocation security check"""
    can_proceed: bool
    requires_reapproval: bool
    reason: Optional[str] = None
    changes_detected: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "can_proceed": self.can_proceed,
            "requires_reapproval": self.requires_reapproval,
            "reason": self.reason,
            "changes_detected": self.changes_detected
        }


@dataclass
class ChangeDetectionResult:
    """Result of change detection between tool versions"""
    has_changes: bool
    version_changed: bool = False
    permissions_changed: bool = False
    provider_changed: bool = False
    new_permissions: List[Permission] = field(default_factory=list)
    removed_permissions: List[Permission] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_changes": self.has_changes,
            "version_changed": self.version_changed,
            "permissions_changed": self.permissions_changed,
            "provider_changed": self.provider_changed,
            "new_permissions": [p.to_dict() for p in self.new_permissions],
            "removed_permissions": [p.to_dict() for p in self.removed_permissions]
        }


@dataclass
class KeyConfig:
    """Configuration for cryptographic keys"""
    private_key_path: Optional[str] = None
    public_key_path: Optional[str] = None
    key_algorithm: str = "RS256"
    key_size: int = 2048
    auto_generate: bool = True

@dataclass
class StorageConfig:
    """Configuration for approval storage"""
    storage_type: str = "file"  # file, database, memory
    storage_path: Optional[str] = None
    encryption_enabled: bool = True
    backup_enabled: bool = True
    retention_days: int = 365

@dataclass
class ClientOptions:
    """Additional client options"""
    timeout_seconds: int = 30
    retry_attempts: int = 3
    enable_caching: bool = True
    cache_ttl_seconds: int = 300
    enable_metrics: bool = True

@dataclass
class ETDIClientConfig:
    """Configuration for ETDI client"""
    security_level: SecurityLevel = SecurityLevel.ENHANCED
    oauth_config: Optional[Dict[str, Any]] = None
    key_config: Optional[KeyConfig] = None
    storage_config: Optional[StorageConfig] = None
    options: Optional[ClientOptions] = None
    verification_cache_ttl: int = 300  # 5 minutes
    allow_non_etdi_tools: bool = True
    show_unverified_tools: bool = False
    enable_request_signing: bool = False  # Only enabled in STRICT mode by default
    
    def __post_init__(self):
        """Convert string security level to enum if needed"""
        if isinstance(self.security_level, str):
            self.security_level = SecurityLevel(self.security_level)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "security_level": self.security_level.value,
            "oauth_config": self.oauth_config,
            "storage_config": self.storage_config,
            "verification_cache_ttl": self.verification_cache_ttl,
            "allow_non_etdi_tools": self.allow_non_etdi_tools,
            "show_unverified_tools": self.show_unverified_tools
        }


@dataclass
class OAuthConfig:
    """OAuth provider configuration"""
    provider: str
    client_id: str
    client_secret: str
    domain: str
    audience: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "domain": self.domain,
            "audience": self.audience,
            "scopes": self.scopes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthConfig":
        return cls(
            provider=data["provider"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            domain=data["domain"],
            audience=data.get("audience"),
            scopes=data.get("scopes", [])
        )