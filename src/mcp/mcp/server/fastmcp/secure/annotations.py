"""
Secure annotations for MCP tools, resources, and prompts.

These annotations extend the standard MCP annotations with security features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from mcp.types import ToolAnnotations, ResourceAnnotations, PromptAnnotations


class AuthMethod(Enum):
    """Supported authentication methods."""
    JWT = "jwt"
    CERTIFICATE = "certificate"
    TEE_ATTESTATION = "tee"
    OAUTH = "oauth"
    API_KEY = "api_key"
    MTLS = "mtls"  # Mutual TLS


@dataclass
class SecureAnnotations:
    """
    Base security annotations that can be attached to tools, resources, or prompts.
    
    These annotations enable security features like authentication, encryption,
    and attestation for MCP operations.
    """
    
    # Authentication settings
    require_auth: bool = False
    auth_methods: list[AuthMethod] = field(default_factory=lambda: [AuthMethod.JWT])
    required_permissions: set[str] = field(default_factory=set)
    require_mutual_auth: bool = False  # Bidirectional authentication
    
    # Encryption settings
    encrypt_input: bool = False
    encrypt_output: bool = False
    encryption_algorithm: str = "AES-256-GCM"
    key_exchange_method: str = "ECDH"  # ECDH, RSA, Pre-shared
    
    # Tool/Server attestation
    require_tool_attestation: bool = False
    tool_certificate_fingerprint: Optional[str] = None
    attestation_type: Optional[str] = None  # "software", "sgx", "sev", "trustzone"
    tool_signature_required: bool = False
    
    # Client verification
    verify_client_certificate: bool = False
    trusted_client_issuers: list[str] = field(default_factory=list)
    client_attestation_required: bool = False
    
    # Audit and compliance
    audit_log: bool = True
    audit_include_inputs: bool = False
    audit_include_outputs: bool = False
    audit_retention_days: int = 90
    
    # Rate limiting
    rate_limit: Optional[int] = None  # requests per minute
    rate_limit_per_client: bool = True
    burst_limit: Optional[int] = None
    
    # Data handling
    security_level: str = "standard"  # "standard", "high", "critical"
    data_classification: str = "public"  # "public", "internal", "confidential", "secret"
    compliance_tags: list[str] = field(default_factory=list)  # ["HIPAA", "PCI-DSS", "GDPR", "SOC2"]
    
    # Session management
    session_timeout_minutes: int = 60
    require_session_binding: bool = False  # Bind session to client IP/fingerprint
    max_concurrent_sessions: Optional[int] = None
    
    # Advanced security
    require_replay_protection: bool = False
    max_request_age_seconds: int = 300  # For replay protection
    require_integrity_check: bool = True  # Verify message integrity
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "require_auth": self.require_auth,
            "auth_methods": [method.value for method in self.auth_methods],
            "required_permissions": list(self.required_permissions),
            "require_mutual_auth": self.require_mutual_auth,
            "encrypt_input": self.encrypt_input,
            "encrypt_output": self.encrypt_output,
            "encryption_algorithm": self.encryption_algorithm,
            "key_exchange_method": self.key_exchange_method,
            "require_tool_attestation": self.require_tool_attestation,
            "tool_certificate_fingerprint": self.tool_certificate_fingerprint,
            "attestation_type": self.attestation_type,
            "tool_signature_required": self.tool_signature_required,
            "verify_client_certificate": self.verify_client_certificate,
            "trusted_client_issuers": self.trusted_client_issuers,
            "client_attestation_required": self.client_attestation_required,
            "audit_log": self.audit_log,
            "audit_include_inputs": self.audit_include_inputs,
            "audit_include_outputs": self.audit_include_outputs,
            "security_level": self.security_level,
            "data_classification": self.data_classification,
            "compliance_tags": self.compliance_tags,
            "session_timeout_minutes": self.session_timeout_minutes,
            "require_session_binding": self.require_session_binding,
            "require_replay_protection": self.require_replay_protection,
            "require_integrity_check": self.require_integrity_check,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecureAnnotations:
        """Create from dictionary."""
        auth_methods = [AuthMethod(m) for m in data.get("auth_methods", ["jwt"])]
        return cls(
            require_auth=data.get("require_auth", False),
            auth_methods=auth_methods,
            required_permissions=set(data.get("required_permissions", [])),
            require_mutual_auth=data.get("require_mutual_auth", False),
            encrypt_input=data.get("encrypt_input", False),
            encrypt_output=data.get("encrypt_output", False),
            encryption_algorithm=data.get("encryption_algorithm", "AES-256-GCM"),
            key_exchange_method=data.get("key_exchange_method", "ECDH"),
            require_tool_attestation=data.get("require_tool_attestation", False),
            tool_certificate_fingerprint=data.get("tool_certificate_fingerprint"),
            attestation_type=data.get("attestation_type"),
            tool_signature_required=data.get("tool_signature_required", False),
            verify_client_certificate=data.get("verify_client_certificate", False),
            trusted_client_issuers=data.get("trusted_client_issuers", []),
            client_attestation_required=data.get("client_attestation_required", False),
            audit_log=data.get("audit_log", True),
            security_level=data.get("security_level", "standard"),
            data_classification=data.get("data_classification", "public"),
            compliance_tags=data.get("compliance_tags", []),
        )


class SecureToolAnnotations(ToolAnnotations):
    """
    Tool annotations with integrated security features.
    
    This extends the standard ToolAnnotations with security metadata.
    """
    
    def __init__(
        self,
        secure: Optional[SecureAnnotations] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.secure = secure or SecureAnnotations()
        
        # Store security annotations in extensions
        if not hasattr(self, 'extensions'):
            self.extensions = {}
        self.extensions["security"] = self.secure.to_dict()
    
    @classmethod
    def create(
        cls,
        # Security parameters
        require_auth: bool = False,
        auth_methods: Optional[list[AuthMethod]] = None,
        required_permissions: Optional[set[str]] = None,
        encrypt_io: bool = False,
        require_mutual_auth: bool = False,
        security_level: str = "standard",
        
        # Standard tool annotation parameters
        audience: Optional[list[str]] = None,
        capabilities: Optional[dict[str, Any]] = None,
        **kwargs
    ) -> SecureToolAnnotations:
        """
        Factory method to create secure tool annotations.
        
        Args:
            require_auth: Whether to require authentication
            auth_methods: List of accepted authentication methods
            required_permissions: Set of required permissions
            encrypt_io: Whether to encrypt input/output
            require_mutual_auth: Whether to require bidirectional authentication
            security_level: Security level (standard/high/critical)
            audience: Target audience for the tool
            capabilities: Tool capabilities
            **kwargs: Additional security parameters
        """
        secure_annotations = SecureAnnotations(
            require_auth=require_auth,
            auth_methods=auth_methods or [AuthMethod.JWT],
            required_permissions=required_permissions or set(),
            encrypt_input=encrypt_io,
            encrypt_output=encrypt_io,
            require_mutual_auth=require_mutual_auth,
            security_level=security_level,
            **kwargs
        )
        
        return cls(
            secure=secure_annotations,
            audience=audience,
            capabilities=capabilities
        )


class SecureResourceAnnotations(ResourceAnnotations):
    """
    Resource annotations with integrated security features.
    
    This extends the standard ResourceAnnotations with security metadata.
    """
    
    def __init__(
        self,
        secure: Optional[SecureAnnotations] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.secure = secure or SecureAnnotations()
        
        # Store security annotations in extensions
        if not hasattr(self, 'extensions'):
            self.extensions = {}
        self.extensions["security"] = self.secure.to_dict()
    
    @classmethod
    def create(
        cls,
        # Security parameters
        require_auth: bool = False,
        data_classification: str = "public",
        encrypt_io: bool = False,
        audit_access: bool = True,
        
        # Standard resource annotation parameters
        content_type: Optional[str] = None,
        cache_control: Optional[str] = None,
        **kwargs
    ) -> SecureResourceAnnotations:
        """
        Factory method to create secure resource annotations.
        
        Args:
            require_auth: Whether to require authentication
            data_classification: Data classification level
            encrypt_io: Whether to encrypt input/output
            audit_access: Whether to audit resource access
            content_type: Resource content type
            cache_control: Cache control headers
            **kwargs: Additional security parameters
        """
        secure_annotations = SecureAnnotations(
            require_auth=require_auth,
            data_classification=data_classification,
            encrypt_input=encrypt_io,
            encrypt_output=encrypt_io,
            audit_log=audit_access,
            **kwargs
        )
        
        return cls(
            secure=secure_annotations,
            content_type=content_type,
            cache_control=cache_control
        )


class SecurePromptAnnotations(PromptAnnotations):
    """
    Prompt annotations with integrated security features.
    
    This extends the standard PromptAnnotations with security metadata.
    """
    
    def __init__(
        self,
        secure: Optional[SecureAnnotations] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.secure = secure or SecureAnnotations()
        
        # Store security annotations in extensions
        if not hasattr(self, 'extensions'):
            self.extensions = {}
        self.extensions["security"] = self.secure.to_dict()
    
    @classmethod
    def create(
        cls,
        # Security parameters
        require_auth: bool = False,
        audit_usage: bool = True,
        compliance_tags: Optional[list[str]] = None,
        
        # Standard prompt annotation parameters
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> SecurePromptAnnotations:
        """
        Factory method to create secure prompt annotations.
        
        Args:
            require_auth: Whether to require authentication
            audit_usage: Whether to audit prompt usage
            compliance_tags: Compliance tags (e.g., ["GDPR", "HIPAA"])
            max_tokens: Maximum tokens for prompt
            temperature: Temperature for prompt generation
            **kwargs: Additional security parameters
        """
        secure_annotations = SecureAnnotations(
            require_auth=require_auth,
            audit_log=audit_usage,
            compliance_tags=compliance_tags or [],
            **kwargs
        )
        
        return cls(
            secure=secure_annotations,
            max_tokens=max_tokens,
            temperature=temperature
        )
