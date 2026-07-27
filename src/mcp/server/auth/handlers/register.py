import secrets
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.auth.errors import stringify_pydantic_error
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, RegistrationError, RegistrationErrorCode
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthClientMetadata

# this alias is a no-op; it's just to separate out the types exposed to the
# provider from what we use in the HTTP handler
RegistrationRequest = OAuthClientMetadata


class RegistrationErrorResponse(BaseModel):
    error: RegistrationErrorCode
    error_description: str | None


@dataclass
class RegistrationHandler:
    provider: OAuthAuthorizationServerProvider[Any, Any, Any]
    options: ClientRegistrationOptions

    async def handle(self, request: Request) -> Response:
        # Implements dynamic client registration as defined in https://datatracker.ietf.org/doc/html/rfc7591#section-3.1
        try:
            body = await request.body()
            client_metadata = OAuthClientMetadata.model_validate_json(body)

            # Scope validation is handled below
        except ValidationError as validation_error:
            return PydanticJSONResponse(
                content=RegistrationErrorResponse(
                    error="invalid_client_metadata",
                    error_description=stringify_pydantic_error(validation_error),
                ),
                status_code=400,
            )

        client_id = str(uuid4())

        # If auth method is None, default to client_secret_post
        if client_metadata.token_endpoint_auth_method is None:
            client_metadata.token_endpoint_auth_method = "client_secret_post"
        # This server authenticates token requests with the client secret it mints; it holds
        # no client key to verify a private_key_jwt assertion, so confirming that method would
        # register a client whose every token request is then rejected. Refuse it instead
        # (RFC 7591 §3.2.2), before minting credentials the client could never use.
        if client_metadata.token_endpoint_auth_method == "private_key_jwt":
            return PydanticJSONResponse(
                content=RegistrationErrorResponse(
                    error="invalid_client_metadata",
                    error_description="token_endpoint_auth_method 'private_key_jwt' is not supported",
                ),
                status_code=400,
            )

        client_secret = None
        if client_metadata.token_endpoint_auth_method != "none":  # pragma: no branch
            # cryptographically secure random 32-byte hex string
            client_secret = secrets.token_hex(32)

        if client_metadata.scope is None and self.options.default_scopes is not None:
            client_metadata.scope = " ".join(self.options.default_scopes)
        elif client_metadata.scope is not None and self.options.valid_scopes is not None:
            requested_scopes = set(client_metadata.scope.split())
            valid_scopes = set(self.options.valid_scopes)
            if not requested_scopes.issubset(valid_scopes):  # pragma: no branch
                return PydanticJSONResponse(
                    content=RegistrationErrorResponse(
                        error="invalid_client_metadata",
                        error_description="Requested scopes are not valid: "
                        f"{', '.join(requested_scopes - valid_scopes)}",
                    ),
                    status_code=400,
                )
        if "authorization_code" not in client_metadata.grant_types:
            return PydanticJSONResponse(
                content=RegistrationErrorResponse(
                    error="invalid_client_metadata",
                    error_description="grant_types must include 'authorization_code'",
                ),
                status_code=400,
            )

        # SEP-990 §5.1 / draft-ietf-oauth-identity-assertion-authz-grant §8.1: the ID-JAG flow is
        # for confidential clients provisioned out of band. Refuse to grant it through DCR so a
        # self-registered client cannot reach the identity-assertion provider hook.
        if JWT_BEARER_GRANT_TYPE in client_metadata.grant_types:
            return PydanticJSONResponse(
                content=RegistrationErrorResponse(
                    error="invalid_client_metadata",
                    error_description=(
                        f"grant_types must not include '{JWT_BEARER_GRANT_TYPE}'; "
                        "the identity-assertion grant requires a pre-registered client"
                    ),
                ),
                status_code=400,
            )

        # The MCP spec requires servers to use the authorization `code` flow
        # with PKCE
        if "code" not in client_metadata.response_types:
            return PydanticJSONResponse(
                content=RegistrationErrorResponse(
                    error="invalid_client_metadata",
                    error_description="response_types must include 'code' for authorization_code grant",
                ),
                status_code=400,
            )

        client_id_issued_at = int(time.time())
        # RFC 7591 §3.2.1: client_secret_expires_at is REQUIRED whenever a client_secret is
        # issued, with 0 (not omission) meaning it never expires; a public client gets none.
        client_secret_expires_at = None
        if client_secret is not None:
            client_secret_expires_at = (
                client_id_issued_at + self.options.client_secret_expiry_seconds
                if self.options.client_secret_expiry_seconds is not None
                else 0
            )

        # RFC 7591 §3.2.1: the response returns all registered metadata about the client, so
        # the record is the whole validated request plus the credentials minted here - built
        # from the request's dump so no metadata field can be silently omitted from the echo.
        client_info = OAuthClientInformationFull.model_validate(
            {
                **client_metadata.model_dump(),
                "client_id": client_id,
                "client_id_issued_at": client_id_issued_at,
                "client_secret": client_secret,
                "client_secret_expires_at": client_secret_expires_at,
            }
        )
        try:
            # Register client
            await self.provider.register_client(client_info)

            # Return client information
            return PydanticJSONResponse(content=client_info, status_code=201)
        except RegistrationError as e:
            # Handle registration errors as defined in RFC 7591 Section 3.2.2
            return PydanticJSONResponse(
                content=RegistrationErrorResponse(error=e.error, error_description=e.error_description),
                status_code=400,
            )
