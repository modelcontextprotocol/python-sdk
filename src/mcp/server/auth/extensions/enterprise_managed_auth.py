"""
Server-side Enterprise Managed Authorization (SEP-990).

Implements JWT validation for ID-JAG tokens and JWT bearer grant handling.
"""

import logging
import time
from typing import Any

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Models
# ============================================================================


class JWTValidationConfig(BaseModel):
    """Configuration for JWT validation."""

    trusted_idp_issuers: list[str] = Field(
        ...,
        description="List of trusted IdP issuer URLs",
    )

    server_auth_issuer: str = Field(
        ...,
        description="This server's authorization server issuer URL",
    )

    server_resource_id: str = Field(
        ...,
        description="This server's resource identifier",
    )

    jwks_uri: str | None = Field(
        default=None,
        description="JWKS URI for key verification (if single IdP)",
    )

    jwks_cache_ttl: int = Field(
        default=3600,
        description="JWKS cache TTL in seconds",
    )

    allowed_algorithms: list[str] = Field(
        default=["RS256", "ES256"],
        description="Allowed JWT signing algorithms",
    )

    replay_prevention_enabled: bool = Field(
        default=True,
        description="Enable JTI-based replay prevention",
    )

    replay_cache_ttl: int = Field(
        default=3600,
        description="Replay cache TTL in seconds",
    )

    clock_skew_seconds: int = Field(
        default=60,
        description="Allowed clock skew for exp/iat validation",
    )


class IDJAGClaims(BaseModel):
    """Validated ID-JAG claims."""

    model_config = {"extra": "allow"}

    # JWT header
    typ: str

    # Required claims
    jti: str
    iss: str
    sub: str
    aud: str
    resource: str
    client_id: str
    exp: int
    iat: int

    # Optional claims
    scope: str | None = None
    email: str | None = None


# ============================================================================
# Replay Prevention
# ============================================================================


class ReplayPreventionStore:
    """In-memory store for replay prevention (production should use Redis/similar)."""

    def __init__(self, ttl: int = 3600):
        self._used_jtis: dict[str, float] = {}
        self._ttl = ttl

    def mark_used(self, jti: str) -> None:
        """Mark a JTI as used."""
        self._cleanup()
        self._used_jtis[jti] = time.time()

    def is_used(self, jti: str) -> bool:
        """Check if a JTI has been used."""
        self._cleanup()
        return jti in self._used_jtis

    def _cleanup(self) -> None:
        """Remove expired entries."""
        now = time.time()
        self._used_jtis = {
            jti: timestamp for jti, timestamp in self._used_jtis.items() if now - timestamp < self._ttl
        }


# ============================================================================
# JWT Validator
# ============================================================================


class IDJAGValidator:
    """Validator for ID-JAG tokens."""

    def __init__(self, config: JWTValidationConfig):
        self.config = config
        self.replay_store = ReplayPreventionStore(ttl=config.replay_cache_ttl)

        # Initialize JWKS client if provided
        self.jwks_client: PyJWKClient | None = None
        if config.jwks_uri:
            self.jwks_client = PyJWKClient(
                config.jwks_uri,
                cache_keys=True,
                max_cached_keys=16,
                cache_jwk_set=True,
                lifespan=config.jwks_cache_ttl,
            )

    def validate_id_jag(
        self,
        id_jag: str,
        expected_client_id: str,
    ) -> IDJAGClaims:
        """
        Validate an ID-JAG token.

        Args:
            id_jag: The ID-JAG token to validate
            expected_client_id: The client_id from client authentication

        Returns:
            Validated ID-JAG claims

        Raises:
            jwt.InvalidTokenError: If validation fails
            ValueError: If claims are invalid
        """
        # Step 1: Decode and get header
        header = jwt.get_unverified_header(id_jag)

        # Validate typ header
        if header.get("typ") != "oauth-id-jag+jwt":
            raise ValueError(f"Invalid typ header: expected 'oauth-id-jag+jwt', got '{header.get('typ')}'")

        # Step 2: Get signing key
        if self.jwks_client:
            signing_key = self.jwks_client.get_signing_key_from_jwt(id_jag)
            key = signing_key.key
        else:
            # For testing/development - decode without verification
            logger.warning("No JWKS client configured - skipping signature verification")
            key = None

        # Step 3: Decode and verify JWT
        try:
            claims = jwt.decode(
                id_jag,
                key,
                algorithms=self.config.allowed_algorithms,
                options={
                    "verify_signature": key is not None,
                    "verify_exp": True,
                    "verify_iat": True,
                },
                leeway=self.config.clock_skew_seconds,
            )
        except jwt.ExpiredSignatureError:
            raise ValueError("ID-JAG has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid ID-JAG: {e}")

        # Step 4: Validate issuer
        if claims.get("iss") not in self.config.trusted_idp_issuers:
            raise ValueError(f"Untrusted issuer: {claims.get('iss')}")

        # Step 5: Validate audience
        if claims.get("aud") != self.config.server_auth_issuer:
            raise ValueError(
                f"Invalid audience: expected '{self.config.server_auth_issuer}', "
                f"got '{claims.get('aud')}'"
            )

        # Step 6: Validate resource
        if claims.get("resource") != self.config.server_resource_id:
            raise ValueError(
                f"Invalid resource: expected '{self.config.server_resource_id}', "
                f"got '{claims.get('resource')}'"
            )

        # Step 7: Validate client_id
        if claims.get("client_id") != expected_client_id:
            raise ValueError(
                f"client_id mismatch: expected '{expected_client_id}', " f"got '{claims.get('client_id')}'"
            )

        # Step 8: Check for replay (if enabled)
        jti = claims.get("jti")
        if not jti:
            raise ValueError("Missing jti claim")

        if self.config.replay_prevention_enabled:
            if self.replay_store.is_used(jti):
                raise ValueError(f"Token replay detected: jti '{jti}' already used")
            self.replay_store.mark_used(jti)

        # Step 9: Create validated claims object
        claims["typ"] = header["typ"]
        return IDJAGClaims.model_validate(claims)

    async def handle_jwt_bearer_grant(
        self,
        assertion: str,
        client_id: str,
    ) -> dict[str, Any]:
        """
        Handle JWT bearer grant request.

        Args:
            assertion: The ID-JAG assertion
            client_id: Authenticated client ID

        Returns:
            Token response dict

        Raises:
            ValueError: If validation fails
        """
        # Validate ID-JAG
        claims = self.validate_id_jag(assertion, client_id)

        # TODO: Generate and return access token
        # This is where you'd integrate with your token generation logic
        logger.info(
            "JWT bearer grant validated successfully",
            extra={
                "client_id": client_id,
                "sub": claims.sub,
                "scope": claims.scope,
            },
        )

        return {
            "token_type": "Bearer",
            "access_token": "generated_access_token_here",
            "expires_in": 3600,
            "scope": claims.scope,
        }
