"""Multi-protocol auth: adapter for Starlette and Mutual TLS placeholder verifier."""

import logging
import time
from typing import Any, cast

from starlette.authentication import AuthCredentials, AuthenticationBackend
from starlette.requests import HTTPConnection, Request

from mcp.server.auth.dpop import DPoPProofVerifier, InMemoryJTIReplayStore
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.verifiers import (
    APIKeyVerifier,
    CredentialVerifier,
    MultiProtocolAuthBackend,
    OAuthTokenVerifier,
)

logger = logging.getLogger(__name__)


class MutualTLSVerifier:
    """Placeholder verifier for Mutual TLS.

    Does not validate client certificates; returns None. Real mTLS validation
    would inspect the TLS connection for client certificate and verify it.
    """

    async def verify(
        self,
        request: Any,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        return None


def build_multiprotocol_backend(
    oauth_token_verifier: Any,
    api_key_valid_keys: set[str],
    api_key_scopes: list[str] | None = None,
    dpop_enabled: bool = False,
) -> tuple[MultiProtocolAuthBackend, DPoPProofVerifier | None]:
    """Build MultiProtocolAuthBackend with OAuth, API Key, and mTLS (placeholder) verifiers.

    Args:
        oauth_token_verifier: Token verifier for OAuth introspection.
        api_key_valid_keys: Set of valid API keys.
        api_key_scopes: Scopes to grant for API key authentication.
        dpop_enabled: Whether to enable DPoP proof verification.

    Returns:
        Tuple of (MultiProtocolAuthBackend, DPoPProofVerifier or None).
    """
    oauth_verifier = OAuthTokenVerifier(oauth_token_verifier)
    api_key_verifier = APIKeyVerifier(
        valid_keys=api_key_valid_keys,
        scopes=api_key_scopes or [],
    )
    mtls_verifier: CredentialVerifier = MutualTLSVerifier()
    backend = MultiProtocolAuthBackend(verifiers=[oauth_verifier, api_key_verifier, mtls_verifier])

    dpop_verifier: DPoPProofVerifier | None = None
    if dpop_enabled:
        dpop_verifier = DPoPProofVerifier(jti_store=InMemoryJTIReplayStore())

    return backend, dpop_verifier


class MultiProtocolAuthBackendAdapter(AuthenticationBackend):
    """Starlette AuthenticationBackend that wraps MultiProtocolAuthBackend.

    Converts AccessToken from backend.verify() into (AuthCredentials, AuthenticatedUser).
    Optionally verifies DPoP proofs when dpop_verifier is provided.
    """

    def __init__(
        self,
        backend: MultiProtocolAuthBackend,
        dpop_verifier: DPoPProofVerifier | None = None,
    ) -> None:
        self._backend = backend
        self._dpop_verifier = dpop_verifier

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, AuthenticatedUser] | None:
        request = cast(Request, conn)

        # Log DPoP status
        dpop_header = request.headers.get("dpop")
        if self._dpop_verifier is not None:
            if dpop_header:
                logger.info("DPoP proof present, verification enabled")
            else:
                logger.debug("DPoP verification enabled but no DPoP header in request")
        elif dpop_header:
            logger.debug("DPoP header present but verification not enabled (ignoring)")

        result = await self._backend.verify(request, dpop_verifier=self._dpop_verifier)

        if result is None:
            if dpop_header and self._dpop_verifier is not None:
                logger.warning("Authentication failed (DPoP proof may be invalid)")
            else:
                logger.debug("Authentication failed (no valid credentials)")
            return None

        if result.expires_at is not None and result.expires_at < int(time.time()):
            logger.warning("Token expired for client_id=%s", result.client_id)
            return None

        # Log successful authentication
        if dpop_header and self._dpop_verifier is not None:
            logger.info("Authentication successful with DPoP (client_id=%s)", result.client_id)
        else:
            logger.info("Authentication successful (client_id=%s)", result.client_id)

        return (
            AuthCredentials(result.scopes or []),
            AuthenticatedUser(result),
        )
