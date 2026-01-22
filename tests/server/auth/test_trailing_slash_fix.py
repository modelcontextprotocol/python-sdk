"""Tests for OAuth metadata URL trailing slash handling.

These tests verify that trailing slashes are properly stripped from OAuth metadata URLs
to ensure compliance with RFC 8414 §3.3 and RFC 9728 §3, which require that the issuer/
resource URL in the metadata response must be identical to the URL used for discovery.

These tests would fail on main (before the fix) but pass on this branch.
"""

import httpx
import pytest
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.routes import build_metadata, create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from tests.server.fastmcp.auth.test_auth_integration import MockOAuthProvider


def test_build_metadata_strips_trailing_slash_from_issuer():
    """Test that build_metadata strips trailing slash from issuer URL when serialized.

    Pydantic's AnyHttpUrl automatically adds trailing slashes to bare hostnames.
    This test verifies that we strip them during serialization to comply with RFC 8414 §3.3.
    """
    # Use a bare hostname URL which Pydantic will add a trailing slash to
    issuer_url = AnyHttpUrl("http://localhost:8000")

    metadata = build_metadata(
        issuer_url=issuer_url,
        service_documentation_url=None,
        client_registration_options=ClientRegistrationOptions(enabled=False),
        revocation_options=RevocationOptions(enabled=False),
    )

    # The serialized issuer should NOT have a trailing slash
    serialized = metadata.model_dump(mode="json")
    assert serialized["issuer"] == "http://localhost:8000"
    assert not serialized["issuer"].endswith("/")


def test_build_metadata_strips_trailing_slash_from_issuer_with_path():
    """Test that build_metadata strips trailing slash from issuer URL with path when serialized."""
    # URL with path that has trailing slash
    issuer_url = AnyHttpUrl("http://localhost:8000/auth/")

    metadata = build_metadata(
        issuer_url=issuer_url,
        service_documentation_url=None,
        client_registration_options=ClientRegistrationOptions(enabled=False),
        revocation_options=RevocationOptions(enabled=False),
    )

    # The serialized issuer should NOT have a trailing slash
    serialized = metadata.model_dump(mode="json")
    assert serialized["issuer"] == "http://localhost:8000/auth"
    assert not serialized["issuer"].endswith("/")


def test_build_metadata_endpoints_have_no_double_slashes():
    """Test that endpoint URLs don't have double slashes when issuer has trailing slash."""
    # Use a URL that Pydantic will add trailing slash to
    issuer_url = AnyHttpUrl("http://localhost:8000")

    metadata = build_metadata(
        issuer_url=issuer_url,
        service_documentation_url=None,
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    )

    # All endpoints should be correctly formed without double slashes
    assert str(metadata.authorization_endpoint) == "http://localhost:8000/authorize"
    assert str(metadata.token_endpoint) == "http://localhost:8000/token"
    assert str(metadata.registration_endpoint) == "http://localhost:8000/register"
    assert str(metadata.revocation_endpoint) == "http://localhost:8000/revoke"

    # None should have double slashes
    assert "//" not in str(metadata.authorization_endpoint).replace("http://", "")
    assert "//" not in str(metadata.token_endpoint).replace("http://", "")
    assert "//" not in str(metadata.registration_endpoint).replace("http://", "")
    assert "//" not in str(metadata.revocation_endpoint).replace("http://", "")


def test_protected_resource_metadata_strips_trailing_slash_from_resource():
    """Test that protected resource metadata strips trailing slash from resource URL when serialized.

    RFC 9728 §3 requires that the resource URL in the metadata response must be
    identical to the URL used for discovery.
    """
    # Use a bare hostname URL which Pydantic will add a trailing slash to
    resource_url = AnyHttpUrl("http://localhost:8000")
    auth_server_url = AnyHttpUrl("http://auth.example.com")

    routes = create_protected_resource_routes(
        resource_url=resource_url,
        authorization_servers=[auth_server_url],
    )

    # Extract metadata from the handler
    # The handler is wrapped in CORS middleware, so we need to unwrap it
    route = routes[0]
    # Access the app inside the middleware
    cors_app = route.endpoint
    handler = cors_app.app.func  # type: ignore

    metadata = handler.__self__.metadata  # type: ignore

    # The serialized resource URL should NOT have a trailing slash
    serialized = metadata.model_dump(mode="json")
    assert serialized["resource"] == "http://localhost:8000"
    assert not serialized["resource"].endswith("/")


def test_protected_resource_metadata_strips_trailing_slash_from_authorization_servers():
    """Test that protected resource metadata strips trailing slashes from auth server URLs when serialized."""
    resource_url = AnyHttpUrl("http://localhost:8000/resource")
    # Use bare hostname URLs which Pydantic will add trailing slashes to
    auth_servers = [
        AnyHttpUrl("http://auth1.example.com"),
        AnyHttpUrl("http://auth2.example.com"),
    ]

    routes = create_protected_resource_routes(
        resource_url=resource_url,
        authorization_servers=auth_servers,
    )

    # Extract metadata from the handler
    route = routes[0]
    cors_app = route.endpoint
    handler = cors_app.app.func  # type: ignore
    metadata = handler.__self__.metadata  # type: ignore

    # All serialized authorization server URLs should NOT have trailing slashes
    serialized = metadata.model_dump(mode="json")
    assert serialized["authorization_servers"][0] == "http://auth1.example.com"
    assert serialized["authorization_servers"][1] == "http://auth2.example.com"
    assert not serialized["authorization_servers"][0].endswith("/")
    assert not serialized["authorization_servers"][1].endswith("/")


@pytest.fixture
def oauth_provider():
    """Return a MockOAuthProvider instance for testing."""
    return MockOAuthProvider()


@pytest.fixture
def app(oauth_provider: MockOAuthProvider):
    """Create a Starlette app with OAuth routes using a bare hostname issuer URL."""
    # Use a bare hostname which Pydantic will add a trailing slash to
    # This simulates the real-world scenario that was failing
    issuer_url = AnyHttpUrl("http://localhost:8000")

    auth_routes = create_auth_routes(
        oauth_provider,
        issuer_url=issuer_url,
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    )

    return Starlette(routes=auth_routes)


@pytest.fixture
def client(app: Starlette):
    """Create an HTTP client for the OAuth app."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


@pytest.mark.anyio
async def test_oauth_metadata_endpoint_has_no_trailing_slash_in_issuer(client: httpx.AsyncClient):
    """Test that the OAuth metadata endpoint returns issuer without trailing slash.

    This is the integration test that verifies the fix works end-to-end.
    This test would FAIL on main because the issuer would have a trailing slash.
    """
    response = await client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    metadata = response.json()

    # The issuer should NOT have a trailing slash
    assert metadata["issuer"] == "http://localhost:8000"
    assert not metadata["issuer"].endswith("/")

    # Endpoints should be correctly formed
    assert metadata["authorization_endpoint"] == "http://localhost:8000/authorize"
    assert metadata["token_endpoint"] == "http://localhost:8000/token"
    assert metadata["registration_endpoint"] == "http://localhost:8000/register"
    assert metadata["revocation_endpoint"] == "http://localhost:8000/revoke"


@pytest.fixture
def protected_resource_app():
    """Create a Starlette app with protected resource routes using bare hostname URLs."""
    # Use bare hostname URLs which Pydantic will add trailing slashes to
    resource_url = AnyHttpUrl("http://localhost:9000")
    auth_servers = [AnyHttpUrl("http://auth.example.com")]

    routes = create_protected_resource_routes(
        resource_url=resource_url,
        authorization_servers=auth_servers,
        scopes_supported=["read", "write"],
    )

    return Starlette(routes=routes)


@pytest.fixture
def protected_resource_client(protected_resource_app: Starlette):
    """Create an HTTP client for the protected resource app."""
    transport = httpx.ASGITransport(app=protected_resource_app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:9000")


@pytest.mark.anyio
async def test_protected_resource_metadata_endpoint_has_no_trailing_slashes(
    protected_resource_client: httpx.AsyncClient,
):
    """Test that protected resource metadata endpoint returns URLs without trailing slashes.

    This integration test verifies the fix for protected resource metadata.
    This test would FAIL on main because resource and authorization_servers would have trailing slashes.
    """
    response = await protected_resource_client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    metadata = response.json()

    # The resource URL should NOT have a trailing slash
    assert metadata["resource"] == "http://localhost:9000"
    assert not metadata["resource"].endswith("/")

    # Authorization server URLs should NOT have trailing slashes
    assert metadata["authorization_servers"] == ["http://auth.example.com"]
    for auth_server in metadata["authorization_servers"]:
        assert not auth_server.endswith("/")
