"""
Secure resource implementation with authentication and encryption.
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar, cast

from mcp.server.fastmcp.resources.base import Resource
from mcp.types import Error

from .annotations import AuthMethod, SecureAnnotations, SecureResourceAnnotations
from .identity import ToolIdentity
from .utils import SecureAnnotationProcessor

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import FastMCP

F = TypeVar('F', bound=Callable[..., Any])


class SecureResource(Resource):
    """
    Secure resource with authentication, encryption, and access control.
    
    This extends the base Resource class with security features.
    """
    
    def __init__(
        self,
        secure_annotations: SecureAnnotations,
        tool_identity: Optional[ToolIdentity] = None,
        processor: Optional[SecureAnnotationProcessor] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.secure_annotations = secure_annotations
        self.tool_identity = tool_identity
        self.processor = processor or SecureAnnotationProcessor(tool_identity=tool_identity)
        
        # Add security metadata to the resource
        self._secure_metadata = {
            "data_classification": secure_annotations.data_classification,
            "encryption_required": secure_annotations.encrypt_output,
            "auth_required": secure_annotations.require_auth,
            "compliance_tags": secure_annotations.compliance_tags,
        }
    
    async def read(self) -> str | bytes:
        """
        Read the secure resource with authentication and encryption.
        
        This method:
        1. Verifies client authentication (if required)
        2. Checks access permissions
        3. Reads the resource
        4. Encrypts the content (if required)
        5. Audits the access
        """
        # In production, extract auth from request context
        auth_header = None  # Would come from request context
        
        # Process secure request
        try:
            session, _ = await self.processor.process_secure_request(
                annotations=self.secure_annotations,
                auth_header=auth_header,
                client_cert=None,
                request_data={}
            )
        except Error as e:
            # Audit failed access attempt
            self.processor._audit_log(
                session=None,
                action="resource_access_denied",
                include_data=False,
                data={"uri": self.uri, "error": str(e)}
            )
            raise
        
        # Check specific resource permissions
        if session.client_identity:
            resource_permission = f"resource.read.{self.name or self.uri}"
            if not session.client_identity.has_permission(resource_permission) and \
               not session.client_identity.has_permission("resource.read.*"):
                raise Error(
                    code=403,
                    message=f"Client lacks permission to read resource: {self.uri}"
                )
        
        # Read the actual resource content
        content = await super().read()
        
        # Process secure response (encrypt if required)
        if self.secure_annotations.encrypt_output:
            secure_content = await self.processor.process_secure_response(
                annotations=self.secure_annotations,
                session=session,
                response_data=content
            )
            
            # Convert encrypted response to string/bytes
            if isinstance(secure_content, dict) and "data" in secure_content:
                content = secure_content["data"]
        
        # Audit successful access
        if self.secure_annotations.audit_log:
            self.processor._audit_log(
                session=session,
                action="resource_accessed",
                include_data=self.secure_annotations.audit_include_outputs,
                data={
                    "uri": self.uri,
                    "classification": self.secure_annotations.data_classification,
                    "size": len(content) if isinstance(content, (str, bytes)) else None
                }
            )
        
        return content


def secure_resource(
    uri: str,
    # Security parameters
    require_auth: bool = False,
    data_classification: str = "public",
    encrypt_io: bool = False,
    audit_access: bool = True,
    compliance_tags: Optional[list[str]] = None,
    
    # Standard resource parameters
    name: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> Callable[[F], F]:
    """
    Decorator to create a secure resource with authentication and encryption.
    
    This decorator wraps a function to create a secure MCP resource that supports:
    - Access control and authentication
    - Data classification and compliance
    - Encryption for sensitive data
    - Audit logging
    
    Args:
        uri: Resource URI
        require_auth: Whether to require authentication
        data_classification: Classification level (public/internal/confidential/secret)
        encrypt_io: Whether to encrypt the resource content
        audit_access: Whether to audit resource access
        compliance_tags: Compliance tags (e.g., ["GDPR", "HIPAA"])
        name: Resource name
        title: Resource title
        description: Resource description
        mime_type: MIME type
    
    Example:
        ```python
        @secure_resource(
            "secure://financial/portfolio/{account_id}",
            require_auth=True,
            data_classification="confidential",
            encrypt_io=True,
            compliance_tags=["PCI-DSS", "SOC2"]
        )
        async def get_portfolio(account_id: str) -> dict:
            # Resource implementation
            return {
                "account_id": account_id,
                "balance": 100000,
                "holdings": [...]
            }
        ```
    """
    # Create secure annotations
    secure_annotations = SecureAnnotations(
        require_auth=require_auth,
        data_classification=data_classification,
        encrypt_input=encrypt_io,
        encrypt_output=encrypt_io,
        audit_log=audit_access,
        compliance_tags=compliance_tags or [],
    )
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # This wrapper would be replaced by SecureResource.read in production
            result = await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)
            return result
        
        # Store security metadata on the function
        wrapper._secure_annotations = secure_annotations
        wrapper._resource_uri = uri
        wrapper._is_secure_resource = True
        wrapper._data_classification = data_classification
        wrapper._compliance_tags = compliance_tags or []
        
        return cast(F, wrapper)
    
    return decorator


class SecureResourceTemplate:
    """
    Template for secure resources with dynamic URIs.
    
    Supports resources like "secure://data/{category}/{item_id}"
    """
    
    def __init__(
        self,
        uri_template: str,
        secure_annotations: SecureAnnotations,
        tool_identity: Optional[ToolIdentity] = None,
    ):
        self.uri_template = uri_template
        self.secure_annotations = secure_annotations
        self.tool_identity = tool_identity
        self.processor = SecureAnnotationProcessor(tool_identity=tool_identity)
    
    def create_resource(self, **params) -> SecureResource:
        """
        Create a secure resource instance with the given parameters.
        
        Args:
            **params: Parameters to fill in the URI template
        
        Returns:
            SecureResource instance
        """
        # Format the URI with parameters
        uri = self.uri_template.format(**params)
        
        return SecureResource(
            uri=uri,
            secure_annotations=self.secure_annotations,
            tool_identity=self.tool_identity,
            processor=self.processor,
        )
    
    def validate_access(self, client_identity, params: dict) -> bool:
        """
        Validate if a client can access a resource with given parameters.
        
        Args:
            client_identity: Client identity to validate
            params: Resource parameters
        
        Returns:
            True if access is allowed, False otherwise
        """
        # Check base permissions
        if not client_identity.has_permission(f"resource.read.{self.uri_template}"):
            return False
        
        # Check parameter-specific permissions
        # For example, for "secure://portfolio/{account_id}",
        # check if client can access that specific account
        for param_name, param_value in params.items():
            specific_perm = f"resource.{param_name}.{param_value}"
            if not client_identity.has_permission(specific_perm):
                # Check wildcard permission
                if not client_identity.has_permission(f"resource.{param_name}.*"):
                    return False
        
        return True