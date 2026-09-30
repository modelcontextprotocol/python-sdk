"""OAuth2 Authentication implementation for httpx2.

Implements authorization code flow with PKCE and automatic token refresh.
"""

from mcp_client.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from mcp_client.client.auth.oauth2 import (
    OAuthClientProvider,
    PKCEParameters,
    TokenStorage,
)
from mcp_client.shared.auth import AuthorizationCodeResult

__all__ = [
    "AuthorizationCodeResult",
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenStorage",
]
