"""
OAuth token manager for ETDI server-side operations
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import jwt

from ..types import OAuthConfig, ETDIToolDefinition, SecurityInfo, OAuthInfo
from ..exceptions import OAuthError, TokenValidationError
from ..oauth import OAuthManager, Auth0Provider, OktaProvider, AzureADProvider, CustomOAuthProvider, GenericOAuthProvider

logger = logging.getLogger(__name__)


class TokenManager:
    """
    Manages OAuth tokens for server-side tool registration and validation
    """
    
    def __init__(self, oauth_configs: List[OAuthConfig]):
        """
        Initialize token manager
        
        Args:
            oauth_configs: List of OAuth provider configurations
        """
        self.oauth_manager = OAuthManager()
        self.oauth_configs = {config.provider: config for config in oauth_configs}
        self._token_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize OAuth providers"""
        if self._initialized:
            return
        
        try:
            # Register OAuth providers
            for provider_name, config in self.oauth_configs.items():
                provider = self._create_provider(config)
                self.oauth_manager.register_provider(provider_name, provider)
            
            # Initialize all providers
            await self.oauth_manager.initialize_all()
            
            self._initialized = True
            logger.info(f"Token manager initialized with {len(self.oauth_configs)} providers")
            
        except Exception as e:
            raise OAuthError(f"Failed to initialize token manager: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        if self.oauth_manager:
            await self.oauth_manager.cleanup_all()
        self._initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    def _create_provider(self, config: OAuthConfig):
        """Create OAuth provider instance"""
        provider_type = config.provider.lower()
        
        if provider_type == "auth0":
            return Auth0Provider(config)
        elif provider_type == "okta":
            return OktaProvider(config)
        elif provider_type in ["azure", "azuread", "azure_ad"]:
            return AzureADProvider(config)
        elif provider_type == "custom":
            # Custom provider requires endpoints configuration
            endpoints = getattr(config, 'endpoints', None)
            if not endpoints:
                raise OAuthError("Custom OAuth provider requires 'endpoints' configuration")
            return GenericOAuthProvider(config, endpoints)
        else:
            # Try to create a generic provider if endpoints are provided
            endpoints = getattr(config, 'endpoints', None)
            if endpoints:
                return GenericOAuthProvider(config, endpoints)
            else:
                raise OAuthError(f"Unsupported OAuth provider: {config.provider}. Use 'custom' with endpoints configuration for custom providers.")
    
    async def get_token_for_tool(
        self, 
        tool_definition: ETDIToolDefinition, 
        provider_name: Optional[str] = None
    ) -> str:
        """
        Get OAuth token for a tool
        
        Args:
            tool_definition: Tool definition requiring OAuth token
            provider_name: Specific provider to use (uses first available if None)
            
        Returns:
            JWT token string
            
        Raises:
            OAuthError: If token acquisition fails
        """
        if not self._initialized:
            await self.initialize()
        
        # Determine provider to use
        if not provider_name:
            if not self.oauth_configs:
                raise OAuthError("No OAuth providers configured")
            provider_name = next(iter(self.oauth_configs.keys()))
        
        if provider_name not in self.oauth_configs:
            available = ", ".join(self.oauth_configs.keys())
            raise OAuthError(f"Provider '{provider_name}' not configured. Available: {available}")
        
        try:
            # Get permission scopes from tool
            permissions = tool_definition.get_permission_scopes()
            
            # Check cache first
            cache_key = f"{provider_name}:{tool_definition.id}:{':'.join(sorted(permissions))}"
            cached_token = await self._get_cached_token(cache_key)
            if cached_token:
                return cached_token
            
            # Get new token
            token = await self.oauth_manager.get_token(
                provider_name,
                tool_definition.id,
                permissions
            )
            
            # Cache the token
            await self._cache_token(cache_key, token)
            
            logger.info(f"Obtained OAuth token for tool {tool_definition.id} from {provider_name}")
            return token
            
        except Exception as e:
            logger.error(f"Failed to get token for tool {tool_definition.id}: {e}")
            if isinstance(e, OAuthError):
                raise
            raise OAuthError(f"Token acquisition failed: {e}", provider=provider_name)
    
    async def enhance_tool_with_oauth(
        self, 
        tool_definition: ETDIToolDefinition, 
        provider_name: Optional[str] = None
    ) -> ETDIToolDefinition:
        """
        Enhance a tool definition with OAuth security information
        
        Args:
            tool_definition: Tool definition to enhance
            provider_name: OAuth provider to use
            
        Returns:
            Enhanced tool definition with OAuth token
        """
        try:
            # Get OAuth token for the tool
            token = await self.get_token_for_tool(tool_definition, provider_name)
            
            # Determine provider name
            if not provider_name:
                provider_name = next(iter(self.oauth_configs.keys()))
            
            # Extract token metadata
            token_metadata = await self._extract_token_metadata(token)
            
            # Create OAuth info
            oauth_info = OAuthInfo(
                token=token,
                provider=provider_name,
                issued_at=token_metadata.get("issued_at"),
                expires_at=token_metadata.get("expires_at")
            )
            
            # Create or update security info
            if not tool_definition.security:
                tool_definition.security = SecurityInfo()
            
            tool_definition.security.oauth = oauth_info
            
            logger.info(f"Enhanced tool {tool_definition.id} with OAuth security")
            return tool_definition
            
        except Exception as e:
            logger.error(f"Failed to enhance tool {tool_definition.id} with OAuth: {e}")
            raise OAuthError(f"Tool enhancement failed: {e}")
    
    async def validate_tool_token(self, tool_definition: ETDIToolDefinition) -> bool:
        """
        Validate the OAuth token in a tool definition
        
        Args:
            tool_definition: Tool definition with OAuth token
            
        Returns:
            True if token is valid
        """
        if not tool_definition.security or not tool_definition.security.oauth:
            return False
        
        try:
            oauth_info = tool_definition.security.oauth
            
            expected_claims = {
                "toolId": tool_definition.id,
                "toolVersion": tool_definition.version,
                "requiredPermissions": tool_definition.get_permission_scopes()
            }
            
            result = await self.oauth_manager.validate_token(
                oauth_info.provider,
                oauth_info.token,
                expected_claims
            )
            
            return result.valid
            
        except Exception as e:
            logger.error(f"Error validating token for tool {tool_definition.id}: {e}")
            return False
    
    async def refresh_tool_token(self, tool_definition: ETDIToolDefinition) -> ETDIToolDefinition:
        """
        Refresh the OAuth token for a tool
        
        Args:
            tool_definition: Tool definition with expired token
            
        Returns:
            Tool definition with refreshed token
        """
        if not tool_definition.security or not tool_definition.security.oauth:
            raise OAuthError("Tool has no OAuth token to refresh")
        
        try:
            oauth_info = tool_definition.security.oauth
            
            # Refresh the token
            new_token = await self.oauth_manager.refresh_token(
                oauth_info.provider,
                oauth_info.token
            )
            
            # Update token metadata
            token_metadata = await self._extract_token_metadata(new_token)
            
            # Update OAuth info
            oauth_info.token = new_token
            oauth_info.issued_at = token_metadata.get("issued_at")
            oauth_info.expires_at = token_metadata.get("expires_at")
            
            logger.info(f"Refreshed OAuth token for tool {tool_definition.id}")
            return tool_definition
            
        except Exception as e:
            logger.error(f"Failed to refresh token for tool {tool_definition.id}: {e}")
            raise OAuthError(f"Token refresh failed: {e}")
    
    async def _extract_token_metadata(self, token: str) -> Dict[str, Any]:
        """Extract metadata from JWT token"""
        try:
            # Decode without verification to get claims
            decoded = jwt.decode(token, options={"verify_signature": False})
            
            metadata = {}
            
            # Extract issued at time
            if "iat" in decoded:
                metadata["issued_at"] = datetime.fromtimestamp(decoded["iat"])
            
            # Extract expiration time
            if "exp" in decoded:
                metadata["expires_at"] = datetime.fromtimestamp(decoded["exp"])
            
            return metadata
            
        except jwt.DecodeError:
            return {}
    
    async def _get_cached_token(self, cache_key: str) -> Optional[str]:
        """Get cached token if still valid"""
        async with self._cache_lock:
            cached = self._token_cache.get(cache_key)
            if cached and cached["expires_at"] > datetime.now():
                return cached["token"]
            elif cached:
                # Remove expired entry
                del self._token_cache[cache_key]
        return None
    
    async def _cache_token(self, cache_key: str, token: str) -> None:
        """Cache token with expiration"""
        try:
            # Extract expiration from token
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp = decoded.get("exp")
            expires_at = datetime.fromtimestamp(exp) if exp else datetime.now() + timedelta(hours=1)
            
            async with self._cache_lock:
                self._token_cache[cache_key] = {
                    "token": token,
                    "expires_at": expires_at
                }
        except Exception:
            # If we can't decode, don't cache
            pass
    
    async def batch_enhance_tools(
        self, 
        tools: List[ETDIToolDefinition], 
        provider_name: Optional[str] = None
    ) -> List[ETDIToolDefinition]:
        """
        Enhance multiple tools with OAuth tokens in parallel
        
        Args:
            tools: List of tools to enhance
            provider_name: OAuth provider to use
            
        Returns:
            List of enhanced tools
        """
        tasks = []
        for tool in tools:
            task = asyncio.create_task(
                self.enhance_tool_with_oauth(tool, provider_name)
            )
            tasks.append(task)
        
        enhanced_tools = []
        for i, task in enumerate(tasks):
            try:
                enhanced_tool = await task
                enhanced_tools.append(enhanced_tool)
            except Exception as e:
                logger.error(f"Failed to enhance tool {tools[i].id}: {e}")
                # Add original tool without enhancement
                enhanced_tools.append(tools[i])
        
        return enhanced_tools
    
    async def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired tokens from cache
        
        Returns:
            Number of expired tokens removed
        """
        async with self._cache_lock:
            expired_keys = []
            now = datetime.now()
            
            for key, cached in self._token_cache.items():
                if cached["expires_at"] <= now:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._token_cache[key]
            
            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired tokens")
            
            return len(expired_keys)
    
    def get_provider_names(self) -> List[str]:
        """Get list of configured provider names"""
        return list(self.oauth_configs.keys())
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get token manager statistics
        
        Returns:
            Dictionary with statistics
        """
        async with self._cache_lock:
            cache_size = len(self._token_cache)
            expired_count = sum(
                1 for cached in self._token_cache.values()
                if cached["expires_at"] <= datetime.now()
            )
        
        return {
            "initialized": self._initialized,
            "providers": list(self.oauth_configs.keys()),
            "cache_size": cache_size,
            "expired_tokens": expired_count
        }