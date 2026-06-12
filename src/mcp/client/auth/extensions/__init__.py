"""MCP Client Auth Extensions."""

from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    JWTParameters,
    PrivateKeyJWTOAuthProvider,
    RFC7523OAuthClientProvider,
    SignedJWTParameters,
    static_assertion_provider,
)
from mcp.client.auth.extensions.enterprise_managed_auth import (
    EnterpriseAuthOAuthClientProvider,
    IDJAGClaims,
    IDJAGTokenExchangeResponse,
    TokenExchangeParameters,
    decode_id_jag,
    validate_token_exchange_params,
)

__all__ = [
    "ClientCredentialsOAuthProvider",
    "static_assertion_provider",
    "SignedJWTParameters",
    "PrivateKeyJWTOAuthProvider",
    "JWTParameters",
    "RFC7523OAuthClientProvider",
    "EnterpriseAuthOAuthClientProvider",
    "IDJAGClaims",
    "IDJAGTokenExchangeResponse",
    "TokenExchangeParameters",
    "decode_id_jag",
    "validate_token_exchange_params",
]
