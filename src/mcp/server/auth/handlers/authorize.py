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
from mcp.shared.auth import InvalidRedirectUriError, InvalidScopeError

logger = logging.getLogger(__name__)


class AuthorizationRequest(BaseModel):
    # See https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.1
    client_id: str = Field(..., description="The client ID")
    redirect_uri: AnyUrl | None = Field(None, description="URL to redirect to after authorization")

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


@dataclass
class AuthorizationHandler:
    provider: OAuthAuthorizationServerProvider[Any, Any, Any]

    async def handle(self, request: Request) -> Response:
        # authorization endpoint for the code grant; see https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.1

        state = None
        redirect_uri = None
        client = None
        params = None

        async def error_response(
            error: AuthorizationErrorCode,
            error_description: str | None,
            attempt_load_client: bool = True,
        ):
            # Per https://datatracker.ietf.org/doc/html/rfc6749#section-4.1.2.1: with a valid client and
            # redirect_uri we redirect back with the error in query params, else respond directly in JSON (a
            # case the spec leaves undefined). Errors may predate validation, so fall back to the raw params.
            nonlocal client, redirect_uri, state
            if client is None and attempt_load_client:
                client_id = best_effort_extract_string("client_id", params)
                client = await self.provider.get_client(client_id) if client_id else None
            if redirect_uri is None and client:
                try:
                    if params is not None and "redirect_uri" not in params:
                        raw_redirect_uri = None
                    else:
                        raw_redirect_uri = AnyUrlModel.model_validate(
                            best_effort_extract_string("redirect_uri", params)
                        ).root
                    redirect_uri = client.validate_redirect_uri(raw_redirect_uri)
                except (ValidationError, InvalidRedirectUriError):
                    # invalid redirect_uri: ignore it and return the original error directly
                    pass

            # the error response MUST contain the state specified by the client, if any
            if state is None:
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
            if request.method == "GET":
                params = request.query_params
            else:
                params = await request.form()

            # capture state before validation so even early error responses can echo it
            state = best_effort_extract_string("state", params)

            try:
                auth_request = AuthorizationRequest.model_validate(params)
                state = auth_request.state
            except ValidationError as validation_error:
                error: AuthorizationErrorCode = "invalid_request"
                for e in validation_error.errors():
                    if e["loc"] == ("response_type",) and e["type"] == "literal_error":
                        error = "unsupported_response_type"
                        break
                return await error_response(error, stringify_pydantic_error(validation_error))

            client = await self.provider.get_client(
                auth_request.client_id,
            )
            if not client:
                return await error_response(
                    error="invalid_request",
                    error_description=f"Client ID '{auth_request.client_id}' not found",
                    attempt_load_client=False,
                )

            try:
                redirect_uri = client.validate_redirect_uri(auth_request.redirect_uri)
            except InvalidRedirectUriError as validation_error:
                return await error_response(
                    error="invalid_request",
                    error_description=validation_error.message,
                )

            # unlike client_id/redirect_uri errors above, scope errors may redirect back to the client
            try:
                scopes = client.validate_scope(auth_request.scope)
            except InvalidScopeError as validation_error:
                return await error_response(
                    error="invalid_scope",
                    error_description=validation_error.message,
                )

            auth_params = AuthorizationParams(
                state=state,
                scopes=scopes,
                code_challenge=auth_request.code_challenge,
                redirect_uri=redirect_uri,
                redirect_uri_provided_explicitly=auth_request.redirect_uri is not None,
                resource=auth_request.resource,  # RFC 8707
            )

            try:
                return RedirectResponse(
                    url=await self.provider.authorize(
                        client,
                        auth_params,
                    ),
                    status_code=302,
                    headers={"Cache-Control": "no-store"},
                )
            except AuthorizeError as e:
                return await error_response(error=e.error, error_description=e.error_description)

        except Exception as validation_error:  # pragma: no cover
            logger.exception("Unexpected error in authorization_handler", exc_info=validation_error)
            return await error_response(error="server_error", error_description="An unexpected error occurred")
