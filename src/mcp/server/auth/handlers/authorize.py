import logging
from dataclasses import dataclass
from typing import Any, Literal

# TODO(Marcelo): We should drop the `RootModel`.
from pydantic import AnyUrl, BaseModel, Field, RootModel, ValidationError  # noqa: TID251
from starlette.datastructures import FormData, QueryParams
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mcp.server.auth.errors import stringify_pydantic_error
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.provider import (
    AuthorizationErrorCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    construct_redirect_uri,
)
from mcp.shared.auth import InvalidRedirectUriError

logger = logging.getLogger(__name__)


class AuthorizationRequest(BaseModel):
    # See https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.1
    client_id: str = Field(..., description="The client ID")
    redirect_uri: AnyUrl | None = Field(None, description="URL to redirect to after authorization")

    # see OAuthClientMetadata; we only support `code`
    response_type: Literal["code"] = Field(..., description="Must be 'code' for authorization code flow")
    code_challenge: str = Field(..., description="PKCE code challenge")
    code_challenge_method: Literal["S256"] = Field("S256", description="PKCE code challenge method, must be S256")
    state: str | None = Field(None, description="Optional state parameter")
    scope: str | None = Field(
        None,
        description="Optional scope; if specified, should be a space-separated list of scope strings",
    )
    resource: str | None = Field(
        None,
        description="RFC 8707 resource indicator - the MCP server this token will be used with",
    )


class AuthorizationErrorResponse(BaseModel):
    error: AuthorizationErrorCode
    error_description: str | None
    error_uri: AnyUrl | None = None
    # must be set if provided in the request
    state: str | None = None


def best_effort_extract_string(key: str, params: None | FormData | QueryParams) -> str | None:
    if params is None:  # pragma: no cover
        return None
    value = params.get(key)
    if isinstance(value, str):
        return value
    return None


class AnyUrlModel(RootModel[AnyUrl]):
    root: AnyUrl


def scope_tokens(scope: str | None) -> list[str] | None:
    """Split an RFC 6749 §3.3 scope parameter into its space-delimited tokens.

    An absent or empty parameter is no scope request at all, so both return None and the
    provider applies its default (RFC 6749 §3.3).
    """
    tokens = scope.split() if scope else []
    return tokens or None


@dataclass
class AuthorizationHandler:
    """The authorization endpoint (RFC 6749 §4.1.1) of the SDK-hosted authorization server.

    `valid_scopes` is the scope set this authorization server supports - the same list advertised
    as `scopes_supported` and enforced at dynamic client registration. A request naming any other
    scope is rejected with `invalid_scope`, whichever client sends it. `None` declares no
    server-wide scope set, so every requested scope reaches the provider. A registered client's
    own `scope` is not consulted: RFC 7591 §2 makes it self-asserted metadata, and enforcing it
    would reject the step-up flow, in which a client re-authorizes for scopes beyond its
    registration. Per-client scope policy belongs in `OAuthAuthorizationServerProvider.authorize()`,
    which rejects a request by raising `AuthorizeError` with `error="invalid_scope"`.
    """

    provider: OAuthAuthorizationServerProvider[Any, Any, Any]
    valid_scopes: list[str] | None = None

    async def handle(self, request: Request) -> Response:
        # implements authorization requests for grant_type=code;
        # see https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.1

        state = None
        redirect_uri = None
        client = None
        params = None

        async def error_response(
            error: AuthorizationErrorCode,
            error_description: str | None,
            attempt_load_client: bool = True,
        ):
            # Error responses take two different formats:
            # 1. The request has a valid client ID & redirect_uri: we issue a redirect
            #    back to the redirect_uri with the error response fields as query
            #    parameters. This allows the client to be notified of the error.
            # 2. Otherwise, we return an error response directly to the end user;
            #     we choose to do so in JSON, but this is left undefined in the
            #     specification.
            # See https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.2.1
            #
            # This logic is a bit awkward to handle, because the error might be thrown
            # very early in request validation, before we've done the usual Pydantic
            # validation, loaded the client, etc. To handle this, error_response()
            # contains fallback logic which attempts to load the parameters directly
            # from the request.

            nonlocal client, redirect_uri, state
            if client is None and attempt_load_client:
                # make last-ditch attempt to load the client
                client_id = best_effort_extract_string("client_id", params)
                client = await self.provider.get_client(client_id) if client_id else None
            if redirect_uri is None and client:
                # make last-ditch effort to load the redirect uri
                try:
                    if params is not None and "redirect_uri" not in params:
                        raw_redirect_uri = None
                    else:
                        raw_redirect_uri = AnyUrlModel.model_validate(
                            best_effort_extract_string("redirect_uri", params)
                        ).root
                    redirect_uri = client.validate_redirect_uri(raw_redirect_uri)
                except (ValidationError, InvalidRedirectUriError):
                    # if the redirect URI is invalid, ignore it & just return the
                    # initial error
                    pass

            # the error response MUST contain the state specified by the client, if any
            if state is None:
                # make last-ditch effort to load state
                state = best_effort_extract_string("state", params)

            error_resp = AuthorizationErrorResponse(
                error=error,
                error_description=error_description,
                state=state,
            )

            if redirect_uri and client:
                return RedirectResponse(
                    url=construct_redirect_uri(str(redirect_uri), **error_resp.model_dump(exclude_none=True)),
                    status_code=302,
                    headers={"Cache-Control": "no-store"},
                )
            else:
                return PydanticJSONResponse(
                    status_code=400,
                    content=error_resp,
                    headers={"Cache-Control": "no-store"},
                )

        try:
            # Parse request parameters
            if request.method == "GET":
                # Convert query_params to dict for pydantic validation
                params = request.query_params
            else:
                # Parse form data for POST requests
                params = await request.form()

            # Save state if it exists, even before validation
            state = best_effort_extract_string("state", params)

            try:
                auth_request = AuthorizationRequest.model_validate(params)
                state = auth_request.state  # Update with validated state
            except ValidationError as validation_error:
                error: AuthorizationErrorCode = "invalid_request"
                for e in validation_error.errors():
                    if e["loc"] == ("response_type",) and e["type"] == "literal_error":
                        error = "unsupported_response_type"
                        break
                return await error_response(error, stringify_pydantic_error(validation_error))

            # Get client information
            client = await self.provider.get_client(
                auth_request.client_id,
            )
            if not client:
                # For client_id validation errors, return direct error (no redirect)
                return await error_response(
                    error="invalid_request",
                    error_description=f"Client ID '{auth_request.client_id}' not found",
                    attempt_load_client=False,
                )

            # Validate redirect_uri against client's registered URIs
            try:
                redirect_uri = client.validate_redirect_uri(auth_request.redirect_uri)
            except InvalidRedirectUriError as validation_error:
                # For redirect_uri validation errors, return direct error (no redirect)
                return await error_response(
                    error="invalid_request",
                    error_description=validation_error.message,
                )

            # Enforce the server-wide scope set; scope policy for the client is the provider's,
            # in authorize(). An unsupported scope redirects back with invalid_scope.
            scopes = scope_tokens(auth_request.scope)
            if scopes is not None and self.valid_scopes is not None:
                unsupported = sorted(set(scopes) - set(self.valid_scopes))
                if unsupported:
                    return await error_response(
                        error="invalid_scope",
                        error_description=f"Requested scopes are not valid: {', '.join(unsupported)}",
                    )

            # Setup authorization parameters
            auth_params = AuthorizationParams(
                state=state,
                scopes=scopes,
                code_challenge=auth_request.code_challenge,
                redirect_uri=redirect_uri,
                redirect_uri_provided_explicitly=auth_request.redirect_uri is not None,
                resource=auth_request.resource,  # RFC 8707
            )

            try:
                # Let the provider pick the next URI to redirect to
                return RedirectResponse(
                    url=await self.provider.authorize(
                        client,
                        auth_params,
                    ),
                    status_code=302,
                    headers={"Cache-Control": "no-store"},
                )
            except AuthorizeError as e:
                # Handle authorization errors as defined in RFC 6749 Section 4.1.2.1
                return await error_response(error=e.error, error_description=e.error_description)

        except Exception as validation_error:  # pragma: no cover
            # Catch-all for unexpected errors
            logger.exception("Unexpected error in authorization_handler", exc_info=validation_error)
            return await error_response(error="server_error", error_description="An unexpected error occurred")
