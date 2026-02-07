"""Multi-protocol credential verifiers.

Defines the CredentialVerifier protocol and concrete implementations used by MultiProtocolAuthBackend.
"""

from typing import Any, Protocol

from starlette.requests import Request

from mcp.server.auth.dpop import DPoPProofVerifier, DPoPVerificationError, extract_dpop_proof
from mcp.server.auth.provider import AccessToken, TokenVerifier

BEARER_PREFIX = "Bearer "
DPOP_PREFIX = "DPoP "
APIKEY_HEADER = "x-api-key"  # if found, use it; if not, use Authorization: Bearer <key>


class CredentialVerifier(Protocol):
    """Credential verifier interface.

    Verifies request authentication information. Optionally performs DPoP verification when a verifier is provided.
    """

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        """Verify credentials from an incoming request.

        Args:
            request: Incoming request.
            dpop_verifier: Optional DPoP verifier.

        Returns:
            AccessToken if verification succeeds, otherwise None.
        """
        ...


class OAuthTokenVerifier:
    """OAuth Bearer/DPoP credential verifier.

    Supports both Bearer and DPoP-bound access tokens. When a dpop_verifier is provided, it verifies DPoP proof
    signature and claims (htm/htu/iat/ath). Note: cnf.jkt binding checks are not implemented yet (requires
    AccessToken extension).
    """

    def __init__(self, token_verifier: TokenVerifier) -> None:
        self._token_verifier = token_verifier

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        auth_header = _get_header_ignore_case(request, "authorization")
        if not auth_header:
            return None

        # Determine token type and extract token
        token: str | None = None
        is_dpop_bound = False

        if auth_header.lower().startswith(DPOP_PREFIX.lower()):
            # DPoP-bound access token (Authorization: DPoP <token>)
            token = auth_header[len(DPOP_PREFIX) :].strip()
            is_dpop_bound = True
        elif auth_header.lower().startswith(BEARER_PREFIX.lower()):
            token = auth_header[len(BEARER_PREFIX) :].strip()

        if not token:
            return None

        # Verify the token itself
        access_token = await self._token_verifier.verify_token(token)
        if access_token is None:
            return None

        # DPoP verification if verifier provided and DPoP header present
        if dpop_verifier is not None and isinstance(dpop_verifier, DPoPProofVerifier):
            headers_dict = dict(request.headers)
            dpop_proof = extract_dpop_proof(headers_dict)

            if is_dpop_bound and not dpop_proof:
                # DPoP-bound token requires DPoP proof
                return None

            if dpop_proof:
                try:
                    http_uri = str(request.url)
                    # Use scope to get method for HTTPConnection compatibility
                    http_method = request.scope.get("method", "")

                    await dpop_verifier.verify(
                        dpop_proof,
                        http_method,
                        http_uri,
                        access_token=token,
                    )
                except DPoPVerificationError:
                    return None

        return access_token


def _get_header_ignore_case(request: Request, name: str) -> str | None:
    """Get first header value matching name (case-insensitive)."""
    for key in request.headers:
        if key.lower() == name.lower():
            return request.headers.get(key)
    return None


class APIKeyVerifier:
    """API key credential verifier.

    Prefers reading ``X-API-Key`` header; optionally falls back to ``Authorization: Bearer <key>`` and matches it
    against valid_keys. This verifier does not parse non-standard ``ApiKey`` schemes.

    Optionally assigns ``scopes`` to the verified token, which can satisfy RequireAuthMiddleware's required_scopes.
    """

    def __init__(self, valid_keys: set[str], scopes: list[str] | None = None) -> None:
        self._valid_keys = valid_keys
        self._scopes = scopes if scopes is not None else []

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        api_key: str | None = _get_header_ignore_case(request, APIKEY_HEADER)
        if not api_key:
            auth_header = _get_header_ignore_case(request, "authorization")
            if auth_header and auth_header.strip().lower().startswith(BEARER_PREFIX.lower()):
                bearer_token = auth_header[len(BEARER_PREFIX) :].strip()
                if bearer_token in self._valid_keys:
                    api_key = bearer_token
        if not api_key or api_key not in self._valid_keys:
            return None
        return AccessToken(
            token=api_key,
            client_id="api_key",
            scopes=list(self._scopes),
            expires_at=None,
        )


class MultiProtocolAuthBackend:
    """Multi-protocol authentication backend.

    Iterates over verifiers in order and returns the first successful AccessToken, or None if all fail.
    """

    def __init__(self, verifiers: list[CredentialVerifier]) -> None:
        self._verifiers = verifiers

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        for verifier in self._verifiers:
            result = await verifier.verify(request, dpop_verifier)
            if result is not None:
                return result
        return None
