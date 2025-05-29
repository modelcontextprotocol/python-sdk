"""
Exception classes for ETDI (Enhanced Tool Definition Interface)
"""

from typing import Optional, Dict, Any


class ETDIError(Exception):
    """Base exception for ETDI-related errors"""
    
    def __init__(self, message: str, code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code or "ETDI_ERROR"
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details
        }


class SignatureError(ETDIError):
    """Raised when tool signature verification fails"""
    
    def __init__(self, message: str, tool_id: Optional[str] = None, provider: Optional[str] = None):
        super().__init__(message, "SIGNATURE_INVALID")
        self.tool_id = tool_id
        self.provider = provider
        self.details.update({
            "tool_id": tool_id,
            "provider": provider
        })


class VersionError(ETDIError):
    """Raised when tool version validation fails"""
    
    def __init__(self, message: str, tool_id: Optional[str] = None, 
                 current_version: Optional[str] = None, expected_version: Optional[str] = None):
        super().__init__(message, "VERSION_MISMATCH")
        self.tool_id = tool_id
        self.current_version = current_version
        self.expected_version = expected_version
        self.details.update({
            "tool_id": tool_id,
            "current_version": current_version,
            "expected_version": expected_version
        })


class PermissionError(ETDIError):
    """Raised when permission validation fails"""
    
    def __init__(self, message: str, tool_id: Optional[str] = None, 
                 missing_permissions: Optional[list] = None, unauthorized_permissions: Optional[list] = None):
        super().__init__(message, "PERMISSION_DENIED")
        self.tool_id = tool_id
        self.missing_permissions = missing_permissions or []
        self.unauthorized_permissions = unauthorized_permissions or []
        self.details.update({
            "tool_id": tool_id,
            "missing_permissions": self.missing_permissions,
            "unauthorized_permissions": self.unauthorized_permissions
        })


class OAuthError(ETDIError):
    """Raised when OAuth operations fail"""
    
    def __init__(self, message: str, provider: Optional[str] = None, 
                 oauth_error: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message, "OAUTH_ERROR")
        self.provider = provider
        self.oauth_error = oauth_error
        self.status_code = status_code
        self.details.update({
            "provider": provider,
            "oauth_error": oauth_error,
            "status_code": status_code
        })


class ProviderError(ETDIError):
    """Raised when OAuth provider operations fail"""
    
    def __init__(self, message: str, provider: Optional[str] = None, operation: Optional[str] = None):
        super().__init__(message, "PROVIDER_ERROR")
        self.provider = provider
        self.operation = operation
        self.details.update({
            "provider": provider,
            "operation": operation
        })


class TokenValidationError(ETDIError):
    """Raised when JWT token validation fails"""
    
    def __init__(self, message: str, token_error: Optional[str] = None, 
                 provider: Optional[str] = None, validation_step: Optional[str] = None):
        super().__init__(message, "TOKEN_VALIDATION_FAILED")
        self.token_error = token_error
        self.provider = provider
        self.validation_step = validation_step
        self.details.update({
            "token_error": token_error,
            "provider": provider,
            "validation_step": validation_step
        })


class ApprovalError(ETDIError):
    """Raised when tool approval operations fail"""
    
    def __init__(self, message: str, tool_id: Optional[str] = None, operation: Optional[str] = None):
        super().__init__(message, "APPROVAL_ERROR")
        self.tool_id = tool_id
        self.operation = operation
        self.details.update({
            "tool_id": tool_id,
            "operation": operation
        })


class ConfigurationError(ETDIError):
    """Raised when ETDI configuration is invalid"""
    
    def __init__(self, message: str, config_field: Optional[str] = None, expected_type: Optional[str] = None):
        super().__init__(message, "CONFIGURATION_ERROR")
        self.config_field = config_field
        self.expected_type = expected_type
        self.details.update({
            "config_field": config_field,
            "expected_type": expected_type
        })


class ToolNotFoundError(ETDIError):
    """Raised when a requested tool is not found"""
    
    def __init__(self, message: str, tool_id: Optional[str] = None):
        super().__init__(message, "TOOL_NOT_FOUND")
        self.tool_id = tool_id
        self.details.update({
            "tool_id": tool_id
        })


class ProviderNotFoundError(ETDIError):
    """Raised when an OAuth provider is not found or supported"""
    
    def __init__(self, message: str, provider: Optional[str] = None, available_providers: Optional[list] = None):
        super().__init__(message, "PROVIDER_NOT_FOUND")
        self.provider = provider
        self.available_providers = available_providers or []
        self.details.update({
            "provider": provider,
            "available_providers": self.available_providers
        })


class SecurityLevelError(ETDIError):
    """Raised when security level requirements are not met"""
    
    def __init__(self, message: str, required_level: Optional[str] = None, current_level: Optional[str] = None):
        super().__init__(message, "SECURITY_LEVEL_ERROR")
        self.required_level = required_level
        self.current_level = current_level
        self.details.update({
            "required_level": required_level,
            "current_level": current_level
        })


class VerificationTimeoutError(ETDIError):
    """Raised when tool verification times out"""
    
    def __init__(self, message: str, tool_id: Optional[str] = None, timeout_seconds: Optional[int] = None):
        super().__init__(message, "VERIFICATION_TIMEOUT")
        self.tool_id = tool_id
        self.timeout_seconds = timeout_seconds
        self.details.update({
            "tool_id": tool_id,
            "timeout_seconds": timeout_seconds
        })


class StorageError(ETDIError):
    """Raised when storage operations fail"""
    
    def __init__(self, message: str, operation: Optional[str] = None, storage_type: Optional[str] = None):
        super().__init__(message, "STORAGE_ERROR")
        self.operation = operation
        self.storage_type = storage_type
        self.details.update({
            "operation": operation,
            "storage_type": storage_type
        })


class KeyExchangeError(ETDIError):
    """Raised when cryptographic key exchange fails"""
    
    def __init__(self, message: str, entity_id: Optional[str] = None, protocol: Optional[str] = None):
        super().__init__(message, "KEY_EXCHANGE_ERROR")
        self.entity_id = entity_id
        self.protocol = protocol
        self.details.update({
            "entity_id": entity_id,
            "protocol": protocol
        })


class RequestSigningError(ETDIError):
    """Raised when request signing operations fail"""
    
    def __init__(self, message: str, key_id: Optional[str] = None, operation: Optional[str] = None):
        super().__init__(message, "REQUEST_SIGNING_ERROR")
        self.key_id = key_id
        self.operation = operation
        self.details.update({
            "key_id": key_id,
            "operation": operation
        })