"""
OAuth provider implementations for ETDI
"""

from .base import OAuthProvider
from .manager import OAuthManager
from .auth0 import Auth0Provider
from .okta import OktaProvider
from .azure import AzureADProvider
from .custom import CustomOAuthProvider, GenericOAuthProvider
from .enhanced_provider import EnhancedAuth0Provider, EnhancedOktaProvider, EnhancedAzureProvider
from ..types import OAuthConfig

__all__ = [
    "OAuthProvider",
    "OAuthManager",
    "Auth0Provider",
    "OktaProvider",
    "AzureADProvider",
    "CustomOAuthProvider",
    "GenericOAuthProvider",
    "EnhancedAuth0Provider",
    "EnhancedOktaProvider",
    "EnhancedAzureProvider",
    "OAuthConfig",
]