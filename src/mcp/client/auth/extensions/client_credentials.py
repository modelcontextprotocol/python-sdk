import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import httpx
import jwt
from pydantic import BaseModel, Field

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, OAuthTokenError, TokenStorage
from mcp.shared.auth import OAuthClientMetadata


class JWTParameters(BaseModel):
    """JWT parameters."""

    assertion: str | None = Field(
        default=None,
        description="JWT assertion for JWT authentication. "
        "Will be used instead of generating a new assertion if provided.",
    )

    issuer: str | None = Field(default=None, description="Issuer for JWT assertions.")
    subject: str | None = Field(default=None, description="Subject identifier for JWT assertions.")
    audience: str | None = Field(default=None, description="Audience for JWT assertions.")
    claims: dict[str, Any] | None = Field(default=None, description="Additional claims for JWT assertions.")
    jwt_signing_algorithm: str | None = Field(default="RS256", description="Algorithm for signing JWT assertions.")
    jwt_signing_key: str | None = Field(default=None, description="Private key for JWT signing.")
    jwt_lifetime_seconds: int = Field(default=300, description="Lifetime of generated JWT in seconds.")

    def to_assertion(self, with_audience_fallback: str | None = None) -> str:
        if self.assertion is not None:
            # Prebuilt JWT (e.g. acquired out-of-band)
            assertion = self.assertion
        else:
            if not self.jwt_signing_key:
                raise OAuthFlowError("Missing signing key for JWT bearer grant")  # pragma: no cover
            if not self.issuer:
                raise OAuthFlowError("Missing issuer for JWT bearer grant")  # pragma: no cover
            if not self.subject:
                raise OAuthFlowError("Missing subject for JWT bearer grant")  # pragma: no cover

            audience = self.audience if self.audience else with_audience_fallback
            if not audience:
                raise OAuthFlowError("Missing audience for JWT bearer grant")  # pragma: no cover

            now = int(time.time())
            claims: dict[str, Any] = {
                "iss": self.issuer,
                "sub": self.subject,
                "aud": audience,
                "exp": now + self.jwt_lifetime_seconds,
                "iat": now,
                "jti": str(uuid4()),
            }
            claims.update(self.claims or {})

            assertion = jwt.encode(
                claims,
                self.jwt_signing_key,
                algorithm=self.jwt_signing_algorithm or "RS256",
            )
        return assertion


class RFC7523OAuthClientProvider(OAuthClientProvider):
    """OAuth client provider for RFC7532 clients."""

    jwt_parameters: JWTParameters | None = None

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
        jwt_parameters: JWTParameters | None = None,
    ) -> None:
        super().__init__(server_url, client_metadata, storage, redirect_handler, callback_handler, timeout)
        self.jwt_parameters = jwt_parameters

    async def _exchange_token_authorization_code(
        self, auth_code: str, code_verifier: str, *, token_data: dict[str, Any] | None = None
    ) -> httpx.Request:  # pragma: no cover
        """Build token exchange request for authorization_code flow."""
        token_data = token_data or {}
        if self.context.client_metadata.token_endpoint_auth_method == "private_key_jwt":
            self._add_client_authentication_jwt(token_data=token_data)
        return await super()._exchange_token_authorization_code(auth_code, code_verifier, token_data=token_data)

    async def _perform_authorization(self) -> httpx.Request:  # pragma: no cover
        """Perform the authorization flow."""
        if "urn:ietf:params:oauth:grant-type:jwt-bearer" in self.context.client_metadata.grant_types:
            token_request = await self._exchange_token_jwt_bearer()
            return token_request
        else:
            return await super()._perform_authorization()

    def _add_client_authentication_jwt(self, *, token_data: dict[str, Any]):  # pragma: no cover
        """Add JWT assertion for client authentication to token endpoint parameters."""
        if not self.jwt_parameters:
            raise OAuthTokenError("Missing JWT parameters for private_key_jwt flow")
        if not self.context.oauth_metadata:
            raise OAuthTokenError("Missing OAuth metadata for private_key_jwt flow")

        # We need to set the audience to the issuer identifier of the authorization server
        # https://datatracker.ietf.org/doc/html/draft-ietf-oauth-rfc7523bis-01#name-updates-to-rfc-7523
        issuer = str(self.context.oauth_metadata.issuer)
        assertion = self.jwt_parameters.to_assertion(with_audience_fallback=issuer)

        # When using private_key_jwt, in a client_credentials flow, we use RFC 7523 Section 2.2
        token_data["client_assertion"] = assertion
        token_data["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        # We need to set the audience to the resource server, the audience is difference from the one in claims
        # it represents the resource server that will validate the token
        token_data["audience"] = self.context.get_resource_url()

    async def _exchange_token_jwt_bearer(self) -> httpx.Request:
        """Build token exchange request for JWT bearer grant."""
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info")  # pragma: no cover
        if not self.jwt_parameters:
            raise OAuthFlowError("Missing JWT parameters")  # pragma: no cover
        if not self.context.oauth_metadata:
            raise OAuthTokenError("Missing OAuth metadata")  # pragma: no cover

        # We need to set the audience to the issuer identifier of the authorization server
        # https://datatracker.ietf.org/doc/html/draft-ietf-oauth-rfc7523bis-01#name-updates-to-rfc-7523
        issuer = str(self.context.oauth_metadata.issuer)
        assertion = self.jwt_parameters.to_assertion(with_audience_fallback=issuer)

        token_data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }

        if self.context.should_include_resource_param(self.context.protocol_version):  # pragma: no branch
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:  # pragma: no branch
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx.Request(
            "POST", token_url, data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
