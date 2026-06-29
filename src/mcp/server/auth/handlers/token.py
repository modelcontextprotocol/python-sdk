import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, Field, TypeAdapter, ValidationError
from starlette.requests import Request

from mcp.server.auth.errors import stringify_pydantic_error
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    TokenError,
    TokenErrorCode,
)
from mcp.shared.auth import OAuthToken


class AuthorizationCodeRequest(BaseModel):
    # See https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.3
    grant_type: Literal["authorization_code"]
    code: str = Field(..., description="The authorization code")
    redirect_uri: AnyUrl | None = Field(None, description="Must be the same as redirect URI provided in /authorize")
    client_id: str
    # we use the client_secret param, per https://datatracker.ietf.org/doc/html/rfc6749#section-2.3.1
    client_secret: str | None = None
    # See https://datatracker.ietf.org/doc/html/rfc7636#section-4.5
    code_verifier: str = Field(..., description="PKCE code verifier")
    # RFC 8707 resource indicator
    resource: str | None = Field(None, description="Resource indicator for the token")


class RefreshTokenRequest(BaseModel):
    # See https://datatracker.ietf.org/doc/html/rfc6749#section-6
    grant_type: Literal["refresh_token"]
    refresh_token: str = Field(..., description="The refresh token")
    scope: str | None = Field(None, description="Optional scope parameter")
    client_id: str
    client_secret: str | None = None
    resource: str | None = Field(None, description="Resource indicator for the token")


class JwtBearerRequest(BaseModel):
    # RFC 7523 §2.1 JWT bearer grant. SEP-990 leg 2: client presents the enterprise IdP-issued ID-JAG as `assertion`.
    grant_type: Literal["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assertion: str = Field(..., description="The ID-JAG (a signed JWT) being presented as the grant")
    scope: str | None = Field(None, description="Optional scope parameter")
    client_id: str
    client_secret: str | None = None
    resource: str | None = Field(None, description="Resource indicator for the token")


TokenRequest = Annotated[
    AuthorizationCodeRequest | RefreshTokenRequest | JwtBearerRequest,
    Field(discriminator="grant_type"),
]
token_request_adapter = TypeAdapter[TokenRequest](TokenRequest)


class TokenErrorResponse(BaseModel):
    """See https://datatracker.ietf.org/doc/html/rfc6749#section-5.2"""

    error: TokenErrorCode
    error_description: str | None = None
    error_uri: AnyHttpUrl | None = None


# alias to separate the HTTP response type from the provider's return type
TokenSuccessResponse = OAuthToken


@dataclass
class TokenHandler:
    provider: OAuthAuthorizationServerProvider[Any, Any, Any]
    client_authenticator: ClientAuthenticator
    identity_assertion_enabled: bool = False

    def response(self, obj: TokenSuccessResponse | TokenErrorResponse):
        status_code = 200
        if isinstance(obj, TokenErrorResponse):
            status_code = 400

        return PydanticJSONResponse(
            content=obj,
            status_code=status_code,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )

    async def handle(self, request: Request):
        try:
            client_info = await self.client_authenticator.authenticate_request(request)
        except AuthenticationError as e:
            return PydanticJSONResponse(
                content=TokenErrorResponse(
                    error="invalid_client",
                    error_description=e.message,
                ),
                status_code=401,
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                },
            )

        try:
            form_data = await request.form()
            # TODO(Marcelo): Can someone check if this `dict()` wrapper is necessary?
            token_request = token_request_adapter.validate_python(dict(form_data))
        except ValidationError as validation_error:
            return self.response(
                TokenErrorResponse(
                    error="invalid_request",
                    error_description=stringify_pydantic_error(validation_error),
                )
            )

        if token_request.grant_type not in client_info.grant_types:
            return self.response(
                TokenErrorResponse(
                    error="unsupported_grant_type",
                    error_description=(f"Unsupported grant type (supported grant types are {client_info.grant_types})"),
                )
            )

        tokens: OAuthToken

        match token_request:
            case AuthorizationCodeRequest():
                auth_code = await self.provider.load_authorization_code(client_info, token_request.code)
                if auth_code is None or auth_code.client_id != token_request.client_id:
                    # if code belongs to different client, pretend it doesn't exist
                    return self.response(
                        TokenErrorResponse(
                            error="invalid_grant",
                            error_description="authorization code does not exist",
                        )
                    )

                # enforce expiry per https://datatracker.ietf.org/doc/html/rfc6749#section-10.5
                if auth_code.expires_at < time.time():
                    return self.response(
                        TokenErrorResponse(
                            error="invalid_grant",
                            error_description="authorization code has expired",
                        )
                    )

                # redirect_uri must match /authorize, see https://datatracker.ietf.org/doc/html/rfc6749#section-10.6
                if auth_code.redirect_uri_provided_explicitly:
                    authorize_request_redirect_uri = auth_code.redirect_uri
                else:  # pragma: no cover
                    authorize_request_redirect_uri = None

                # compare as strings to handle AnyUrl vs str mismatches
                token_redirect_str = str(token_request.redirect_uri) if token_request.redirect_uri is not None else None
                auth_redirect_str = (
                    str(authorize_request_redirect_uri) if authorize_request_redirect_uri is not None else None
                )

                if token_redirect_str != auth_redirect_str:
                    return self.response(
                        TokenErrorResponse(
                            error="invalid_request",
                            error_description=("redirect_uri did not match the one used when creating auth code"),
                        )
                    )

                sha256 = hashlib.sha256(token_request.code_verifier.encode()).digest()
                hashed_code_verifier = base64.urlsafe_b64encode(sha256).decode().rstrip("=")

                if hashed_code_verifier != auth_code.code_challenge:
                    # see https://datatracker.ietf.org/doc/html/rfc7636#section-4.6
                    return self.response(
                        TokenErrorResponse(
                            error="invalid_grant",
                            error_description="incorrect code_verifier",
                        )
                    )

                try:
                    tokens = await self.provider.exchange_authorization_code(client_info, auth_code)
                except TokenError as e:
                    return self.response(TokenErrorResponse(error=e.error, error_description=e.error_description))

            case RefreshTokenRequest():
                refresh_token = await self.provider.load_refresh_token(client_info, token_request.refresh_token)
                if refresh_token is None or refresh_token.client_id != token_request.client_id:
                    # if token belongs to different client, pretend it doesn't exist
                    return self.response(
                        TokenErrorResponse(
                            error="invalid_grant",
                            error_description="refresh token does not exist",
                        )
                    )

                if refresh_token.expires_at and refresh_token.expires_at < time.time():
                    return self.response(
                        TokenErrorResponse(
                            error="invalid_grant",
                            error_description="refresh token has expired",
                        )
                    )

                scopes = token_request.scope.split(" ") if token_request.scope else refresh_token.scopes

                for scope in scopes:
                    if scope not in refresh_token.scopes:
                        return self.response(
                            TokenErrorResponse(
                                error="invalid_scope",
                                error_description=(f"cannot request scope `{scope}` not provided by refresh token"),
                            )
                        )

                try:
                    tokens = await self.provider.exchange_refresh_token(client_info, refresh_token, scopes)
                except TokenError as e:
                    return self.response(TokenErrorResponse(error=e.error, error_description=e.error_description))

            case JwtBearerRequest():  # pragma: no branch
                if not self.identity_assertion_enabled:
                    return self.response(
                        TokenErrorResponse(
                            error="unsupported_grant_type",
                            error_description="The JWT bearer grant is not supported by this authorization server",
                        )
                    )

                # SEP-990 §5.1: only confidential clients may present an ID-JAG. ClientAuthenticator already
                # rejects secret-based methods lacking a stored secret; this blocks `none` before the provider hook.
                if not client_info.client_secret:
                    # RFC 6749 §5.2: authenticated but not permitted this grant, so unauthorized_client
                    # rather than invalid_client (which signals failed authentication).
                    return self.response(
                        TokenErrorResponse(
                            error="unauthorized_client",
                            error_description="The JWT bearer grant requires a confidential client",
                        )
                    )

                params = IdentityAssertionParams(
                    assertion=token_request.assertion,
                    scopes=token_request.scope.split(" ") if token_request.scope else None,
                    resource=token_request.resource,
                )
                try:
                    tokens = await self.provider.exchange_identity_assertion(client_info, params)
                except TokenError as e:
                    return self.response(TokenErrorResponse(error=e.error, error_description=e.error_description))

        return self.response(tokens)
