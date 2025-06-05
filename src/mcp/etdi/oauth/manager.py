"""
OAuth manager for coordinating multiple OAuth providers
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type
from datetime import datetime, timedelta

from .base import OAuthProvider
from .auth0 import Auth0Provider
from .okta import OktaProvider
from .azure import AzureADProvider
from ..types import OAuthConfig, VerificationResult
from ..exceptions import OAuthError, ProviderError, ConfigurationError

logger = logging.getLogger(__name__)


class OAuthManager:
    """
    Manages multiple OAuth providers and coordinates token operations
    """
    
    def __init__(self):
        """Initialize OAuth manager"""
        self._providers: Dict[str, OAuthProvider] = {}
        self._provider_configs: Dict[str, OAuthConfig] = {}
        self._initialized = False
        self._provider_classes: Dict[str, Type[OAuthProvider]] = {
            "auth0": Auth0Provider,
            "okta": OktaProvider,
            "azure": AzureADProvider,
            "azuread": AzureADProvider,
        }
    
    def register_provider(self, name: str, provider: OAuthProvider) -> None:
        """
        Register an OAuth provider
        
        Args:
            name: Provider name
            provider: Provider instance
        """
        self._providers[name] = provider
        self._provider_configs[name] = provider.config
        logger.info(f"Registered OAuth provider: {name}")
    
    def register_provider_config(self, name: str, config: OAuthConfig) -> None:
        """
        Register an OAuth provider configuration
        
        Args:
            name: Provider name
            config: Provider configuration
        """
        provider_type = config.provider.lower()
        
        if provider_type not in self._provider_classes:
            raise ConfigurationError(f"Unsupported OAuth provider: {config.provider}")
        
        provider_class = self._provider_classes[provider_type]
        provider = provider_class(config)
        
        self.register_provider(name, provider)
    
    async def initialize_all(self) -> None:
        """Initialize all registered providers"""
        if self._initialized:
            return
        
        try:
            for name, provider in self._providers.items():
                try:
                    await provider.initialize()
                    logger.info(f"Initialized OAuth provider: {name}")
                except Exception as e:
                    logger.error(f"Failed to initialize provider {name}: {e}")
                    raise ProviderError(f"Provider {name} initialization failed: {e}", provider=name)
            
            self._initialized = True
            logger.info(f"OAuth manager initialized with {len(self._providers)} providers")
            
        except Exception as e:
            raise OAuthError(f"OAuth manager initialization failed: {e}")
    
    async def cleanup_all(self) -> None:
        """Cleanup all providers"""
        for name, provider in self._providers.items():
            try:
                await provider.cleanup()
                logger.debug(f"Cleaned up OAuth provider: {name}")
            except Exception as e:
                logger.error(f"Error cleaning up provider {name}: {e}")
        
        self._initialized = False
    
    async def get_token(self, provider_name: str, tool_id: str, permissions: List[str]) -> str:
        """
        Get OAuth token from a specific provider
        
        Args:
            provider_name: Name of the provider
            tool_id: Tool identifier
            permissions: Required permissions
            
        Returns:
            OAuth token
            
        Raises:
            ProviderError: If provider not found or token acquisition fails
        """
        if not self._initialized:
            await self.initialize_all()
        
        if provider_name not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ProviderError(
                f"Provider '{provider_name}' not found. Available: {available}",
                provider=provider_name
            )
        
        try:
            provider = self._providers[provider_name]
            token = await provider.get_token(tool_id, permissions)
            logger.info(f"Obtained token for tool {tool_id} from {provider_name}")
            return token
            
        except Exception as e:
            logger.error(f"Failed to get token from {provider_name}: {e}")
            if isinstance(e, OAuthError):
                raise
            raise ProviderError(f"Token acquisition failed: {e}", provider=provider_name)
    
    async def validate_token(
        self, 
        provider_name: str, 
        token: str, 
        expected_claims: Dict[str, Any]
    ) -> VerificationResult:
        """
        Validate OAuth token with a specific provider
        
        Args:
            provider_name: Name of the provider
            token: Token to validate
            expected_claims: Expected token claims
            
        Returns:
            Verification result
            
        Raises:
            ProviderError: If provider not found or validation fails
        """
        if not self._initialized:
            await self.initialize_all()
        
        if provider_name not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ProviderError(
                f"Provider '{provider_name}' not found. Available: {available}",
                provider=provider_name
            )
        
        try:
            provider = self._providers[provider_name]
            result = await provider.validate_token(token, expected_claims)
            logger.debug(f"Validated token with {provider_name}: {result.valid}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to validate token with {provider_name}: {e}")
            if isinstance(e, (OAuthError, ProviderError)):
                raise
            raise ProviderError(f"Token validation failed: {e}", provider=provider_name)
    
    async def refresh_token(self, provider_name: str, token: str) -> str:
        """
        Refresh OAuth token with a specific provider
        
        Args:
            provider_name: Name of the provider
            token: Token to refresh
            
        Returns:
            New token
            
        Raises:
            ProviderError: If provider not found or refresh fails
        """
        if not self._initialized:
            await self.initialize_all()
        
        if provider_name not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ProviderError(
                f"Provider '{provider_name}' not found. Available: {available}",
                provider=provider_name
            )
        
        try:
            provider = self._providers[provider_name]
            new_token = await provider.refresh_token(token)
            logger.info(f"Refreshed token with {provider_name}")
            return new_token
            
        except Exception as e:
            logger.error(f"Failed to refresh token with {provider_name}: {e}")
            if isinstance(e, OAuthError):
                raise
            raise ProviderError(f"Token refresh failed: {e}", provider=provider_name)
    
    def list_providers(self) -> List[str]:
        """
        List all registered provider names
        
        Returns:
            List of provider names
        """
        return list(self._providers.keys())
    
    def get_provider(self, name: str) -> Optional[OAuthProvider]:
        """
        Get a specific provider instance
        
        Args:
            name: Provider name
            
        Returns:
            Provider instance or None if not found
        """
        return self._providers.get(name)
    
    def get_provider_config(self, name: str) -> Optional[OAuthConfig]:
        """
        Get a specific provider configuration
        
        Args:
            name: Provider name
            
        Returns:
            Provider configuration or None if not found
        """
        return self._provider_configs.get(name)
    
    async def test_all_providers(self) -> Dict[str, bool]:
        """
        Test connectivity to all providers
        
        Returns:
            Dictionary mapping provider names to connectivity status
        """
        if not self._initialized:
            await self.initialize_all()
        
        results = {}
        
        for name, provider in self._providers.items():
            try:
                # Try to get provider info or test connectivity
                if hasattr(provider, 'test_connectivity'):
                    success = await provider.test_connectivity()
                else:
                    # Fallback: try to get provider info
                    await provider.get_provider_info()
                    success = True
                
                results[name] = success
                logger.debug(f"Provider {name} connectivity: {'OK' if success else 'FAILED'}")
                
            except Exception as e:
                results[name] = False
                logger.warning(f"Provider {name} connectivity test failed: {e}")
        
        return results
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get OAuth manager statistics
        
        Returns:
            Dictionary with statistics
        """
        stats = {
            "initialized": self._initialized,
            "total_providers": len(self._providers),
            "provider_names": list(self._providers.keys()),
            "supported_provider_types": list(self._provider_classes.keys())
        }
        
        if self._initialized:
            # Test provider connectivity
            connectivity = await self.test_all_providers()
            stats["provider_connectivity"] = connectivity
            stats["healthy_providers"] = sum(1 for status in connectivity.values() if status)
        
        return stats
    
    def create_provider_from_config(self, config: OAuthConfig) -> OAuthProvider:
        """
        Create a provider instance from configuration
        
        Args:
            config: OAuth configuration
            
        Returns:
            Provider instance
            
        Raises:
            ConfigurationError: If provider type is not supported
        """
        provider_type = config.provider.lower()
        
        if provider_type not in self._provider_classes:
            supported = ", ".join(self._provider_classes.keys())
            raise ConfigurationError(
                f"Unsupported OAuth provider: {config.provider}. Supported: {supported}"
            )
        
        provider_class = self._provider_classes[provider_type]
        return provider_class(config)
    
    async def __aenter__(self):
        await self.initialize_all()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_all()