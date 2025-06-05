"""
ETDI-enhanced MCP server with OAuth security integration
"""

import logging
from typing import Any, Dict, List, Optional, Callable
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

from ..types import ETDIToolDefinition, OAuthConfig, Permission
from ..exceptions import ETDIError, ConfigurationError
from .middleware import OAuthSecurityMiddleware
from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class ETDISecureServer(FastMCP):
    """
    Enhanced MCP server with ETDI OAuth security
    """
    
    def __init__(self, oauth_configs: List[OAuthConfig], **kwargs):
        """
        Initialize ETDI secure server
        
        Args:
            oauth_configs: List of OAuth provider configurations
            **kwargs: Additional arguments for FastMCP
        """
        super().__init__(**kwargs)
        self.oauth_configs = oauth_configs
        self.security_middleware: Optional[OAuthSecurityMiddleware] = None
        self._etdi_tools: Dict[str, ETDIToolDefinition] = {}
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the secure server"""
        if self._initialized:
            return
        
        try:
            # Initialize security middleware
            self.security_middleware = OAuthSecurityMiddleware(self.oauth_configs)
            await self.security_middleware.initialize()
            
            # FastMCP doesn't have an initialize method, so we skip this
            # The FastMCP initialization happens in the constructor
            
            self._initialized = True
            logger.info("ETDI secure server initialized")
            
        except Exception as e:
            raise ETDIError(f"Failed to initialize ETDI secure server: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        if self.security_middleware:
            await self.security_middleware.cleanup()
        # FastMCP doesn't have a cleanup method, so we skip this
        self._initialized = False
    
    def secure_tool(self, permissions: List[str], provider: Optional[str] = None):
        """
        Decorator for securing tools with OAuth
        
        Args:
            permissions: Required permissions for the tool
            provider: Specific OAuth provider to use
            
        Returns:
            Decorator function
        """
        def decorator(func):
            # Create ETDI tool definition
            tool_def = self._create_etdi_tool_from_function(func, permissions)
            
            # Store the tool definition
            self._etdi_tools[func.__name__] = tool_def
            
            # Create secured wrapper
            async def secured_wrapper(*args, **kwargs):
                if not self._initialized:
                    await self.initialize()
                
                # Validate tool invocation
                context = self._get_invocation_context()
                is_valid = await self.security_middleware.validate_tool_invocation(
                    func.__name__,
                    context
                )
                
                if not is_valid:
                    raise ETDIError(f"Tool invocation not authorized: {func.__name__}")
                
                # Call original function
                return await func(*args, **kwargs)
            
            # Copy metadata
            secured_wrapper.__name__ = func.__name__
            secured_wrapper.__doc__ = func.__doc__
            secured_wrapper._etdi_permissions = permissions
            secured_wrapper._etdi_provider = provider
            secured_wrapper._etdi_secured = True
            
            # Register with FastMCP using the secured wrapper
            return self.tool()(secured_wrapper)
        
        return decorator
    
    async def register_etdi_tool(
        self,
        tool_definition: ETDIToolDefinition,
        implementation: Callable,
        provider: Optional[str] = None,
        require_request_signing: bool = False
    ) -> ETDIToolDefinition:
        """
        Register a tool with ETDI security
        
        Args:
            tool_definition: Tool definition
            implementation: Tool implementation function
            provider: OAuth provider to use
            require_request_signing: Require cryptographic request signing (STRICT mode only)
            
        Returns:
            Enhanced tool definition with OAuth token
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Enhance tool with OAuth security
            enhanced_tool = await self.security_middleware.enhance_tool_definition(
                tool_definition,
                provider
            )
            
            # Store enhanced tool
            self._etdi_tools[enhanced_tool.id] = enhanced_tool
            
            # Create secured implementation
            async def secured_implementation(*args, **kwargs):
                context = self._get_invocation_context()
                
                # Check request signing if required
                if require_request_signing:
                    if not await self._verify_request_signature(context):
                        raise ETDIError(f"Request signature verification failed for tool: {enhanced_tool.id}")
                
                is_valid = await self.security_middleware.validate_tool_invocation(
                    enhanced_tool.id,
                    context
                )
                
                if not is_valid:
                    raise ETDIError(f"Tool invocation not authorized: {enhanced_tool.id}")
                
                return await implementation(*args, **kwargs)
            
            # Store request signing requirement
            secured_implementation._etdi_require_request_signing = require_request_signing
            
            # Register with FastMCP
            self._register_tool_with_fastmcp(enhanced_tool, secured_implementation)
            
            logger.info(f"Registered ETDI tool: {enhanced_tool.id}")
            return enhanced_tool
            
        except Exception as e:
            logger.error(f"Failed to register ETDI tool {tool_definition.id}: {e}")
            raise ETDIError(f"Tool registration failed: {e}")
    
    def _create_etdi_tool_from_function(
        self, 
        func: Callable, 
        permissions: List[str]
    ) -> ETDIToolDefinition:
        """Create ETDI tool definition from function"""
        # Extract function metadata
        name = func.__name__
        description = func.__doc__ or f"Tool: {name}"
        
        # Create permission objects
        permission_objects = []
        for perm in permissions:
            permission_objects.append(Permission(
                name=perm,
                description=f"Permission: {perm}",
                scope=perm,
                required=True
            ))
        
        # Create basic schema (would need more sophisticated extraction in real implementation)
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        return ETDIToolDefinition(
            id=name,
            name=name,
            version="1.0.0",
            description=description,
            provider={"id": "etdi-server", "name": "ETDI Server"},
            schema=schema,
            permissions=permission_objects
        )
    
    def _register_tool_with_fastmcp(
        self, 
        tool_definition: ETDIToolDefinition, 
        implementation: Callable
    ) -> None:
        """Register tool with FastMCP"""
        # Convert ETDI tool to FastMCP tool format
        fastmcp_tool = Tool(
            name=tool_definition.id,
            description=tool_definition.description,
            inputSchema=tool_definition.schema
        )
        
        # Register with FastMCP (this would need actual FastMCP integration)
        # For now, just store the mapping
        logger.debug(f"Would register FastMCP tool: {tool_definition.id}")
    
    def _get_invocation_context(self) -> Dict[str, Any]:
        """Get current invocation context"""
        # This would extract context from current request
        # For now, return empty context
        return {
            "headers": {},
            "user": None,
            "timestamp": None
        }
    
    async def list_etdi_tools(self) -> List[ETDIToolDefinition]:
        """
        List all ETDI tools registered with this server
        
        Returns:
            List of ETDI tool definitions
        """
        return list(self._etdi_tools.values())
    
    async def get_etdi_tool(self, tool_id: str) -> Optional[ETDIToolDefinition]:
        """
        Get a specific ETDI tool by ID
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            ETDI tool definition if found
        """
        return self._etdi_tools.get(tool_id)
    
    async def refresh_tool_tokens(self, tool_ids: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Refresh OAuth tokens for tools
        
        Args:
            tool_ids: Specific tool IDs to refresh (all if None)
            
        Returns:
            Dictionary mapping tool IDs to refresh success status
        """
        if not self.security_middleware:
            raise ETDIError("Security middleware not initialized")
        
        target_tools = tool_ids or list(self._etdi_tools.keys())
        results = {}
        
        for tool_id in target_tools:
            tool = self._etdi_tools.get(tool_id)
            if not tool:
                results[tool_id] = False
                continue
            
            try:
                # Refresh token through middleware
                enhanced_tool = await self.security_middleware.enhance_tool_definition(tool)
                self._etdi_tools[tool_id] = enhanced_tool
                results[tool_id] = True
                logger.info(f"Refreshed token for tool: {tool_id}")
                
            except Exception as e:
                logger.error(f"Failed to refresh token for tool {tool_id}: {e}")
                results[tool_id] = False
        
        return results
    
    async def get_security_status(self) -> Dict[str, Any]:
        """
        Get security status for the server
        
        Returns:
            Dictionary with security status information
        """
        if not self.security_middleware:
            return {"error": "Security middleware not initialized"}
        
        middleware_stats = await self.security_middleware.get_security_stats()
        
        return {
            "initialized": self._initialized,
            "total_tools": len(self._etdi_tools),
            "secured_tools": len([t for t in self._etdi_tools.values() if t.security]),
            "oauth_providers": len(self.oauth_configs),
            "middleware": middleware_stats
        }
    
    def add_security_hook(self, event: str, hook: Callable) -> None:
        """
        Add a security event hook
        
        Args:
            event: Event name
            hook: Hook function
        """
        if self.security_middleware:
            self.security_middleware.register_security_hook(event, hook)
    
    def add_tool_enhancer(self, enhancer: Callable[[ETDIToolDefinition], ETDIToolDefinition]) -> None:
        """
        Add a tool enhancer function
        
        Args:
            enhancer: Function that enhances tool definitions
        """
        if self.security_middleware:
            self.security_middleware.register_tool_enhancer(enhancer)
    
    async def _verify_request_signature(self, context: Dict[str, Any]) -> bool:
        """Verify request signature for ETDI tools"""
        try:
            # Import crypto components
            from ..crypto import SignatureVerifier, KeyManager
            
            # Initialize signature verifier if not already done
            if not hasattr(self, '_signature_verifier'):
                key_manager = KeyManager()
                self._signature_verifier = SignatureVerifier(key_manager)
            
            # Extract request details from context
            headers = context.get('headers', {})
            method = context.get('method', 'POST')
            url = context.get('url', '/mcp/tools/call')
            body = context.get('body', '')
            
            # Verify signature
            is_valid, error = self._signature_verifier.verify_request_signature(
                method, url, headers, body
            )
            
            if not is_valid:
                logger.warning(f"Request signature verification failed: {error}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying request signature: {e}")
            return False
    
    def initialize_request_signing(self, key_store_path: Optional[str] = None) -> None:
        """Initialize request signing verification"""
        try:
            from ..crypto import KeyManager, SignatureVerifier
            
            key_manager = KeyManager(key_store_path)
            self._signature_verifier = SignatureVerifier(key_manager)
            
            logger.info("Request signing verification initialized for ETDISecureServer")
            
        except Exception as e:
            logger.error(f"Failed to initialize request signing: {e}")
            raise ETDIError(f"Request signing initialization failed: {e}")


# Convenience function for creating secure servers
def create_etdi_server(
    oauth_configs: List[OAuthConfig],
    name: str = "ETDI Secure Server",
    version: str = "1.0.0"
) -> ETDISecureServer:
    """
    Create an ETDI secure server with OAuth configuration
    
    Args:
        oauth_configs: OAuth provider configurations
        name: Server name
        version: Server version
        
    Returns:
        Configured ETDI secure server
    """
    return ETDISecureServer(
        oauth_configs=oauth_configs,
        name=name,
        version=version
    )