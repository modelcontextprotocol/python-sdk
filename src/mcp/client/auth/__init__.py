"""Client-side authentication for MCP HTTP transports.

Two `httpx.Auth` implementations are provided:

- `BearerAuth` — minimal two-method provider (`token()` + optional
  `on_unauthorized()`) for API keys, gateway-managed tokens, service accounts,
  or any scenario where the token comes from an external pipeline.
- `OAuthClientProvider` — full OAuth 2.1 authorization-code flow with PKCE,
  Protected Resource Metadata discovery (RFC 9728), dynamic client registration,
  and automatic token refresh.

Both are `httpx.Auth` subclasses and plug into the same `auth` parameter.
"""

from mcp.client.auth.bearer import BearerAuth, TokenSource, UnauthorizedContext, UnauthorizedHandler
from mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError, UnauthorizedError
from mcp.client.auth.oauth2 import (
    OAuthClientProvider,
    PKCEParameters,
    TokenStorage,
)

__all__ = [
    "BearerAuth",
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenSource",
    "TokenStorage",
    "UnauthorizedContext",
    "UnauthorizedError",
    "UnauthorizedHandler",
]
