"""OAuth2 authentication for HTTPX: authorization code flow with PKCE and automatic token refresh."""

from mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from mcp.client.auth.oauth2 import (
    OAuthClientProvider,
    PKCEParameters,
    TokenStorage,
)
from mcp.shared.auth import AuthorizationCodeResult

__all__ = [
    "AuthorizationCodeResult",
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenStorage",
]
