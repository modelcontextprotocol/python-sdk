"""
OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

from mcp.client.auth.oauth2 import (
    ClientCredentialsProvider,
    OAuthClientProvider,
    OAuthFlowError,
    OAuthRegistrationError,
    OAuthTokenError,
    PKCEParameters,
    TokenExchangeProvider,
    TokenStorage,
)

__all__ = [
    "ClientCredentialsProvider",
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenExchangeProvider",
    "TokenStorage",
]
