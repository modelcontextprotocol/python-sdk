"""OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

from mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from mcp.client.auth.oauth2 import (
    OAuthAuthorizationRedirect,
    OAuthClientProvider,
    PKCEParameters,
    TokenStorage,
    build_authorization_redirect,
)

__all__ = [
    "OAuthAuthorizationRedirect",
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenStorage",
    "build_authorization_redirect",
]
