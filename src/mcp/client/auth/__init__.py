"""OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

from mcp.client.auth.authlib_adapter import AuthlibAdapterConfig, AuthlibOAuthAdapter
from mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from mcp.client.auth.oauth2 import (
    OAuthClientProvider,
    PKCEParameters,
    TokenStorage,
)

__all__ = [
    "AuthlibAdapterConfig",
    "AuthlibOAuthAdapter",
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenStorage",
]
