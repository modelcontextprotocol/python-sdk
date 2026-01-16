"""Auth components for MCP servers."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import AnyHttpUrl
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route
from starlette.types import ASGIApp

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenVerifier
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions


@dataclass
class AuthComponents:
    """Auth components ready to be used in a Starlette app.

    Attributes:
        middleware: Authentication middleware to add to the app.
        endpoint_wrapper: Wrapper function to protect endpoints with auth.
        routes: OAuth and/or protected resource metadata routes.
    """

    middleware: list[Middleware]
    endpoint_wrapper: Callable[[Any], ASGIApp]
    routes: list[Route]


def build_auth_components(
    token_verifier: TokenVerifier,
    *,
    required_scopes: Sequence[str] = (),
    # OAuth AS routes (only if MCP server IS the auth server)
    auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
    issuer_url: AnyHttpUrl | None = None,
    service_documentation_url: AnyHttpUrl | None = None,
    client_registration_options: ClientRegistrationOptions | None = None,
    revocation_options: RevocationOptions | None = None,
    # Protected resource metadata routes
    resource_server_url: AnyHttpUrl | None = None,
) -> AuthComponents:
    """
    Build auth components for a Starlette app.

    This function creates the middleware, endpoint wrapper, and routes needed
    to add OAuth 2.0 authentication to an MCP server.

    Args:
        token_verifier: Verifies bearer tokens from requests.
        required_scopes: Scopes required to access the MCP endpoint.
        auth_server_provider: OAuth AS provider (if MCP server is the auth server).
        issuer_url: OAuth issuer URL (required if auth_server_provider is set).
        service_documentation_url: URL to service documentation.
        client_registration_options: Options for dynamic client registration.
        revocation_options: Options for token revocation.
        resource_server_url: Resource server URL for protected resource metadata.

    Returns:
        AuthComponents containing middleware, endpoint wrapper, and routes.

    Example:
        >>> auth = build_auth_components(
        ...     token_verifier=my_verifier,
        ...     required_scopes=["mcp:read"],
        ...     resource_server_url="https://mcp.example.com",
        ... )
        >>> app = create_streamable_http_app(
        ...     session_manager,
        ...     middleware=auth.middleware,
        ...     endpoint_wrapper=auth.endpoint_wrapper,
        ...     additional_routes=auth.routes,
        ... )
    """
    routes: list[Route] = []

    # Build middleware
    middleware = [
        Middleware(
            AuthenticationMiddleware,
            backend=BearerAuthBackend(token_verifier),
        ),
        Middleware(AuthContextMiddleware),
    ]

    # Add OAuth AS routes if provider is configured
    if auth_server_provider is not None:
        if issuer_url is None:
            raise ValueError("issuer_url is required when auth_server_provider is set")
        routes.extend(
            create_auth_routes(
                provider=auth_server_provider,
                issuer_url=issuer_url,
                service_documentation_url=service_documentation_url,
                client_registration_options=client_registration_options,
                revocation_options=revocation_options,
            )
        )

    # Add protected resource metadata routes if resource_server_url is set
    if resource_server_url is not None:
        authorization_servers = [issuer_url] if issuer_url is not None else []
        routes.extend(
            create_protected_resource_routes(
                resource_url=resource_server_url,
                authorization_servers=authorization_servers,
                scopes_supported=list(required_scopes) if required_scopes else None,
            )
        )

    # Build endpoint wrapper
    resource_metadata_url = None
    if resource_server_url is not None:
        resource_metadata_url = build_resource_metadata_url(resource_server_url)

    def endpoint_wrapper(app: Any) -> ASGIApp:
        return RequireAuthMiddleware(app, list(required_scopes), resource_metadata_url)

    return AuthComponents(
        middleware=middleware,
        endpoint_wrapper=endpoint_wrapper,
        routes=routes,
    )
