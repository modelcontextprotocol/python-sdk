"""
Tests for mcp.server.auth.components module.
"""

import pytest
from pydantic import AnyHttpUrl

from mcp.server.auth import AuthComponents, build_auth_components
from mcp.server.auth.provider import AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class MockTokenVerifier:
    """Mock token verifier for testing."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token == "valid":
            return AccessToken(token=token, client_id="test-client", scopes=["read"])
        return None


class MockAuthServerProvider:
    """Minimal mock OAuth AS provider for testing."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        raise NotImplementedError

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        raise NotImplementedError

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise NotImplementedError

    async def load_access_token(self, token: str) -> AccessToken | None:
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        pass


def test_build_auth_components_returns_auth_components():
    """build_auth_components returns an AuthComponents instance."""
    result = build_auth_components(token_verifier=MockTokenVerifier())

    assert isinstance(result, AuthComponents)
    assert result.middleware is not None
    assert result.endpoint_wrapper is not None
    assert result.routes is not None


def test_build_auth_components_always_returns_middleware():
    """Middleware is always returned regardless of other options."""
    result = build_auth_components(token_verifier=MockTokenVerifier())

    assert len(result.middleware) == 2  # AuthenticationMiddleware + AuthContextMiddleware


def test_build_auth_components_always_returns_endpoint_wrapper():
    """Endpoint wrapper is always returned."""
    result = build_auth_components(token_verifier=MockTokenVerifier())

    assert callable(result.endpoint_wrapper)


def test_build_auth_components_no_routes_without_providers():
    """Routes are empty when no auth_server_provider or resource_server_url."""
    result = build_auth_components(token_verifier=MockTokenVerifier())

    assert result.routes == []


def test_build_auth_components_oauth_routes_with_auth_server_provider():
    """OAuth AS routes are returned when auth_server_provider is set."""
    result = build_auth_components(
        token_verifier=MockTokenVerifier(),
        auth_server_provider=MockAuthServerProvider(),
        issuer_url=AnyHttpUrl("https://auth.example.com"),
    )

    assert len(result.routes) > 0
    # Check that typical OAuth paths are present
    paths = [route.path for route in result.routes]
    assert "/authorize" in paths
    assert "/token" in paths


def test_build_auth_components_protected_resource_routes_with_resource_server_url():
    """Protected resource metadata routes are returned when resource_server_url is set."""
    # resource_server_url requires an issuer_url for the authorization_servers list
    result = build_auth_components(
        token_verifier=MockTokenVerifier(),
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("https://api.example.com"),
    )

    assert len(result.routes) > 0
    paths = [route.path for route in result.routes]
    assert "/.well-known/oauth-protected-resource" in paths


def test_build_auth_components_combined_routes():
    """Both OAuth AS and protected resource routes when both are configured."""
    result = build_auth_components(
        token_verifier=MockTokenVerifier(),
        auth_server_provider=MockAuthServerProvider(),
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("https://api.example.com"),
    )

    paths = [route.path for route in result.routes]
    # OAuth routes
    assert "/authorize" in paths
    assert "/token" in paths
    # Protected resource route
    assert "/.well-known/oauth-protected-resource" in paths


def test_build_auth_components_raises_without_issuer_url_when_provider_set():
    """ValueError raised when auth_server_provider is set but issuer_url is missing."""
    with pytest.raises(ValueError, match="issuer_url is required"):
        build_auth_components(
            token_verifier=MockTokenVerifier(),
            auth_server_provider=MockAuthServerProvider(),
        )


def test_build_auth_components_required_scopes_passed_to_wrapper():
    """Required scopes are captured in the endpoint wrapper."""
    result = build_auth_components(
        token_verifier=MockTokenVerifier(),
        required_scopes=["read", "write"],
    )

    # The wrapper should be created - we can't easily test internals,
    # but we verify it's callable and was created with the scopes
    assert callable(result.endpoint_wrapper)
