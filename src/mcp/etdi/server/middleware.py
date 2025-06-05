"""
OAuth security middleware for ETDI server-side operations
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

from ..types import ETDIToolDefinition, OAuthConfig, SecurityInfo, OAuthInfo
from ..exceptions import OAuthError, ConfigurationError
from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class OAuthSecurityMiddleware:
    """
    Middleware for adding OAuth security to MCP server tools
    """
    
    def __init__(self, oauth_configs: List[OAuthConfig]):
        """
        Initialize OAuth security middleware
        
        Args:
            oauth_configs: List of OAuth provider configurations
        """
        self.oauth_configs = oauth_configs
        self.token_manager: Optional[TokenManager] = None
        self._initialized = False
        self._tool_enhancers: List[Callable] = []
        self._security_hooks: Dict[str, List[Callable]] = {}
    
    async def initialize(self) -> None:
        """Initialize the middleware"""
        if self._initialized:
            return
        
        try:
            # Initialize token manager
            self.token_manager = TokenManager(self.oauth_configs)
            await self.token_manager.initialize()
            
            self._initialized = True
            logger.info("OAuth security middleware initialized")
            
        except Exception as e:
            raise OAuthError(f"Failed to initialize OAuth middleware: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        if self.token_manager:
            await self.token_manager.cleanup()
        self._initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def enhance_tool_definition(
        self, 
        tool_definition: ETDIToolDefinition,
        provider_name: Optional[str] = None
    ) -> ETDIToolDefinition:
        """
        Enhance a tool definition with OAuth security
        
        Args:
            tool_definition: Tool definition to enhance
            provider_name: Specific OAuth provider to use
            
        Returns:
            Enhanced tool definition with OAuth token
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Get OAuth token for the tool
            enhanced_tool = await self.token_manager.enhance_tool_with_oauth(
                tool_definition,
                provider_name
            )
            
            # Apply any registered enhancers
            for enhancer in self._tool_enhancers:
                enhanced_tool = await enhancer(enhanced_tool)
            
            # Trigger security hooks
            await self._trigger_hooks('tool_enhanced', {
                'tool_id': enhanced_tool.id,
                'provider': enhanced_tool.security.oauth.provider if enhanced_tool.security and enhanced_tool.security.oauth else None
            })
            
            logger.info(f"Enhanced tool {tool_definition.id} with OAuth security")
            return enhanced_tool
            
        except Exception as e:
            logger.error(f"Failed to enhance tool {tool_definition.id}: {e}")
            raise OAuthError(f"Tool enhancement failed: {e}")
    
    async def validate_tool_invocation(
        self, 
        tool_id: str, 
        context: Dict[str, Any]
    ) -> bool:
        """
        Validate a tool invocation request
        
        Args:
            tool_id: Tool identifier
            context: Invocation context (headers, user info, etc.)
            
        Returns:
            True if invocation is allowed
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Extract OAuth token from context
            auth_header = context.get('headers', {}).get('authorization', '')
            if not auth_header.startswith('Bearer '):
                logger.warning(f"Missing or invalid authorization header for tool {tool_id}")
                return False
            
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            
            # Validate token (this would need tool definition for full validation)
            # For now, just check if token is present and not obviously invalid
            if not token or len(token) < 10:
                logger.warning(f"Invalid token format for tool {tool_id}")
                return False
            
            # Trigger validation hooks
            await self._trigger_hooks('tool_invocation_validated', {
                'tool_id': tool_id,
                'context': context,
                'token_present': True
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating tool invocation for {tool_id}: {e}")
            return False
    
    def register_tool_enhancer(self, enhancer: Callable[[ETDIToolDefinition], ETDIToolDefinition]) -> None:
        """
        Register a tool enhancer function
        
        Args:
            enhancer: Function that takes and returns an ETDIToolDefinition
        """
        self._tool_enhancers.append(enhancer)
    
    def register_security_hook(self, event: str, hook: Callable) -> None:
        """
        Register a security event hook
        
        Args:
            event: Event name
            hook: Hook function
        """
        if event not in self._security_hooks:
            self._security_hooks[event] = []
        self._security_hooks[event].append(hook)
    
    async def _trigger_hooks(self, event: str, data: Dict[str, Any]) -> None:
        """Trigger registered hooks for an event"""
        if event in self._security_hooks:
            for hook in self._security_hooks[event]:
                try:
                    if asyncio.iscoroutinefunction(hook):
                        await hook(data)
                    else:
                        hook(data)
                except Exception as e:
                    logger.error(f"Error in security hook for {event}: {e}")
    
    async def refresh_tool_tokens(self, tool_ids: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Refresh OAuth tokens for tools
        
        Args:
            tool_ids: Specific tool IDs to refresh (all if None)
            
        Returns:
            Dictionary mapping tool IDs to refresh success status
        """
        if not self._initialized:
            await self.initialize()
        
        # This would need access to tool registry to implement fully
        # For now, return empty result
        logger.info("Token refresh requested but not implemented without tool registry")
        return {}
    
    async def get_security_stats(self) -> Dict[str, Any]:
        """
        Get security middleware statistics
        
        Returns:
            Dictionary with security statistics
        """
        if not self.token_manager:
            return {"error": "Middleware not initialized"}
        
        token_stats = await self.token_manager.get_stats()
        
        return {
            "initialized": self._initialized,
            "oauth_providers": len(self.oauth_configs),
            "provider_names": [config.provider for config in self.oauth_configs],
            "tool_enhancers": len(self._tool_enhancers),
            "security_hooks": {event: len(hooks) for event, hooks in self._security_hooks.items()},
            "token_manager": token_stats
        }
    
    def create_tool_decorator(self, permissions: List[str], provider: Optional[str] = None):
        """
        Create a decorator for securing tools with OAuth
        
        Args:
            permissions: Required permissions for the tool
            provider: Specific OAuth provider to use
            
        Returns:
            Decorator function
        """
        def decorator(func):
            # Store OAuth metadata on the function
            func._etdi_permissions = permissions
            func._etdi_provider = provider
            func._etdi_secured = True
            
            async def wrapper(*args, **kwargs):
                # This would implement pre-invocation security checks
                # For now, just call the original function
                return await func(*args, **kwargs)
            
            # Copy metadata
            wrapper.__name__ = func.__name__
            wrapper.__doc__ = func.__doc__
            wrapper._etdi_permissions = permissions
            wrapper._etdi_provider = provider
            wrapper._etdi_secured = True
            
            return wrapper
        
        return decorator
    
    def secure_tool(self, permissions: List[str], provider: Optional[str] = None):
        """
        Decorator for securing tools with OAuth (alias for create_tool_decorator)
        
        Args:
            permissions: Required permissions for the tool
            provider: Specific OAuth provider to use
            
        Returns:
            Decorator function
        """
        return self.create_tool_decorator(permissions, provider)


class ETDISecurityContext:
    """
    Security context for ETDI operations
    """
    
    def __init__(self):
        self.current_tool: Optional[str] = None
        self.current_token: Optional[str] = None
        self.current_permissions: List[str] = []
        self.validation_time: Optional[datetime] = None
    
    def set_tool_context(self, tool_id: str, token: str, permissions: List[str]) -> None:
        """Set the current tool context"""
        self.current_tool = tool_id
        self.current_token = token
        self.current_permissions = permissions
        self.validation_time = datetime.now()
    
    def clear_context(self) -> None:
        """Clear the current context"""
        self.current_tool = None
        self.current_token = None
        self.current_permissions = []
        self.validation_time = None
    
    def has_permission(self, permission: str) -> bool:
        """Check if current context has a permission"""
        return permission in self.current_permissions
    
    def is_valid(self) -> bool:
        """Check if context is valid"""
        return (
            self.current_tool is not None and
            self.current_token is not None and
            self.validation_time is not None
        )