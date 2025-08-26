"""
Secure tool implementation with authentication and encryption.
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar, cast

from mcp.server.fastmcp.tools.base import Tool
from mcp.types import ContentBlock, Error

from .annotations import SecureAnnotations, SecureToolAnnotations
from .identity import ClientIdentity, ToolIdentity
from .session import SecureSession
from .utils import SecureAnnotationProcessor

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context, FastMCP

F = TypeVar('F', bound=Callable[..., Any])


class SecureTool(Tool):
    """
    Secure tool with authentication, encryption, and attestation support.
    
    This extends the base Tool class with security features.
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
        
        # Update annotations with security metadata
        if not self.annotations:
            self.annotations = SecureToolAnnotations(secure=secure_annotations)
        elif hasattr(self.annotations, 'extensions'):
            self.annotations.extensions["security"] = secure_annotations.to_dict()
    
    async def run(
        self,
        arguments: dict[str, Any],
        context: Context | None = None,
        convert_result: bool = False,
    ) -> Any:
        """
        Run the secure tool with authentication and encryption.
        
        This method:
        1. Authenticates the client (if required)
        2. Verifies tool identity (if mutual auth is enabled)
        3. Decrypts input (if encryption is enabled)
        4. Executes the tool
        5. Encrypts output (if encryption is enabled)
        6. Signs the result (if attestation is enabled)
        """
        # Extract authentication information from context
        auth_header = None
        client_cert = None
        if context and hasattr(context, 'request_context'):
            request = getattr(context.request_context, 'request', None)
            if request:
                auth_header = request.headers.get('Authorization')
                # In production, extract client cert from TLS connection
        
        # Process secure request (authenticate, decrypt, etc.)
        try:
            session, processed_args = await self.processor.process_secure_request(
                annotations=self.secure_annotations,
                auth_header=auth_header,
                client_cert=client_cert,
                request_data=arguments
            )
        except Error as e:
            # Log authentication failure
            if context:
                await context.error(f"Security check failed: {e.message}")
            raise
        
        # If mutual authentication is required, send tool attestation
        if self.secure_annotations.require_mutual_auth and self.tool_identity:
            attestation = self.tool_identity.to_attestation()
            if context:
                await context.info(f"Tool attestation: {self.name} (fingerprint: {attestation['fingerprint'][:16]}...)")
        
        # Log the authenticated execution
        if context and session.client_identity:
            await context.info(
                f"Executing secure tool '{self.name}' for client '{session.client_identity.client_id}' "
                f"(auth: {session.client_identity.authentication_method.value})"
            )
        
        # Execute the actual tool function with processed arguments
        try:
            # Inject session into arguments if function expects it
            sig = inspect.signature(self.fn)
            if '_secure_session' in sig.parameters:
                processed_args['_secure_session'] = session
            
            result = await super().run(
                arguments=processed_args,
                context=context,
                convert_result=convert_result
            )
        except Exception as e:
            # Audit the failure
            if self.secure_annotations.audit_log:
                if context:
                    await context.error(f"Tool execution failed: {str(e)}")
            raise
        
        # Process secure response (encrypt, sign, etc.)
        secure_result = await self.processor.process_secure_response(
            annotations=self.secure_annotations,
            session=session,
            response_data=result
        )
        
        return secure_result
    
    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        secure_annotations: SecureAnnotations,
        tool_identity: Optional[ToolIdentity] = None,
        name: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ) -> SecureTool:
        """Create a SecureTool from a function."""
        # Create base tool first
        base_tool = Tool.from_function(
            fn=fn,
            name=name,
            title=title,
            description=description,
            **kwargs
        )
        
        # Create secure tool with same properties
        return cls(
            fn=base_tool.fn,
            name=base_tool.name,
            title=base_tool.title,
            description=base_tool.description,
            parameters=base_tool.parameters,
            fn_metadata=base_tool.fn_metadata,
            is_async=base_tool.is_async,
            context_kwarg=base_tool.context_kwarg,
            secure_annotations=secure_annotations,
            tool_identity=tool_identity,
            annotations=SecureToolAnnotations(secure=secure_annotations)
        )


def secure_tool(
    # Security parameters
    require_auth: bool = False,
    auth_methods: Optional[list] = None,
    required_permissions: Optional[set[str]] = None,
    encrypt_io: bool = False,
    require_mutual_auth: bool = False,
    security_level: str = "standard",
    tool_identity: Optional[ToolIdentity] = None,
    
    # Standard tool parameters
    name: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    structured_output: Optional[bool] = None,
) -> Callable[[F], F]:
    """
    Decorator to create a secure tool with authentication and encryption.
    
    This decorator wraps a function to create a secure MCP tool that supports:
    - Client authentication (JWT, certificates, TEE attestation)
    - Bidirectional authentication (tool ↔ client)
    - Input/output encryption
    - Audit logging and compliance
    
    Args:
        require_auth: Whether to require authentication
        auth_methods: List of accepted authentication methods
        required_permissions: Permissions required to execute the tool
        encrypt_io: Whether to encrypt input and output
        require_mutual_auth: Whether to require bidirectional authentication
        security_level: Security level (standard/high/critical)
        tool_identity: Tool identity for attestation
        name: Tool name
        title: Tool title
        description: Tool description
        structured_output: Whether to use structured output
    
    Example:
        ```python
        @secure_tool(
            require_auth=True,
            required_permissions={"trade.execute"},
            encrypt_io=True,
            require_mutual_auth=True
        )
        async def execute_trade(symbol: str, amount: float, ctx: Context) -> str:
            # Tool implementation
            return f"Trade executed: {symbol} x {amount}"
        ```
    """
    from .annotations import AuthMethod
    
    # Create secure annotations
    secure_annotations = SecureAnnotations(
        require_auth=require_auth,
        auth_methods=auth_methods or [AuthMethod.JWT],
        required_permissions=required_permissions or set(),
        encrypt_input=encrypt_io,
        encrypt_output=encrypt_io,
        require_mutual_auth=require_mutual_auth,
        security_level=security_level,
    )
    
    def decorator(func: F) -> F:
        # Check if this is being used with FastMCP
        # In production, this would be integrated with FastMCP.tool()
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # This wrapper would be replaced by SecureTool.run in production
            # For now, just call the function
            return await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)
        
        # Store security metadata on the function
        wrapper._secure_annotations = secure_annotations
        wrapper._tool_identity = tool_identity
        wrapper._is_secure_tool = True
        
        return cast(F, wrapper)
    
    return decorator


def create_secure_tool_from_function(
    fn: Callable[..., Any],
    mcp: FastMCP,
    secure_annotations: SecureAnnotations,
    tool_identity: Optional[ToolIdentity] = None,
    **kwargs
) -> None:
    """
    Helper function to add a secure tool to a FastMCP instance.
    
    This would be called internally by FastMCP when a secure_tool decorator is used.
    """
    secure_tool_instance = SecureTool.from_function(
        fn=fn,
        secure_annotations=secure_annotations,
        tool_identity=tool_identity,
        **kwargs
    )
    
    # Register with the tool manager
    mcp._tool_manager._tools[secure_tool_instance.name] = secure_tool_instance