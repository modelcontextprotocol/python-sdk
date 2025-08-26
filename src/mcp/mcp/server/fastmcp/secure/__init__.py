"""
Secure annotations and decorators for MCP tools, resources, and prompts.

This module provides enhanced security features including:
- Bidirectional authentication (client ↔ tool)
- End-to-end encryption
- Tool attestation and signing
- Rate limiting and audit logging
"""

from .annotations import (
    AuthMethod,
    SecureAnnotations,
    SecureToolAnnotations,
    SecureResourceAnnotations,
    SecurePromptAnnotations,
)
from .tool import SecureTool, secure_tool
from .resource import SecureResource, secure_resource
from .prompt import SecurePrompt, secure_prompt
from .identity import ToolIdentity, ClientIdentity, create_tool_identity
from .session import SecureSession, SessionManager
from .utils import SecureAnnotationProcessor, encrypt_data, decrypt_data

__all__ = [
    # Annotations
    "AuthMethod",
    "SecureAnnotations",
    "SecureToolAnnotations",
    "SecureResourceAnnotations",
    "SecurePromptAnnotations",
    
    # Secure wrappers
    "SecureTool",
    "SecureResource",
    "SecurePrompt",
    
    # Decorators
    "secure_tool",
    "secure_resource",
    "secure_prompt",
    
    # Identity & Session
    "ToolIdentity",
    "ClientIdentity",
    "SecureSession",
    "SessionManager",
    "create_tool_identity",
    
    # Utils
    "SecureAnnotationProcessor",
    "encrypt_data",
    "decrypt_data",
]