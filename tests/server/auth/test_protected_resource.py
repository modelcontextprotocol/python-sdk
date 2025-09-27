"""
Integration tests for MCP Oauth Protected Resource.
"""

import httpx
import pytest
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.routes import build_resource_metadata_url, create_protected_resource_routes


@pytest.fixture
def test_app():
    """Fixture to create protected resource routes for testing."""

    # Create the protected resource routes
    protected_resource_routes = create_protected_resource_routes(
        resource_url=AnyHttpUrl("https://example.com/resource"),
        authorization_servers=[AnyHttpUrl("https://auth.example.com/authorization")],
        scopes_supported=["read", "write"],
        resource_name="Example Resource",
        resource_documentation=AnyHttpUrl("https://docs.example.com/resource"),
    )

    app = Starlette(routes=protected_resource_routes)
    return app


@pytest.fixture
async def test_client(test_app: Starlette):
    """Fixture to create an HTTP client for the protected resource app."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="https://mcptest.com") as client:
        yield client


@pytest.mark.anyio
async def test_metadata_endpoint_with_path(test_client: httpx.AsyncClient):
    """Test the OAuth 2.0 Protected Resource metadata endpoint for path-based resource."""

    # For resource with path "/resource", metadata should be accessible at the path-aware location
    response = await test_client.get("/.well-known/oauth-protected-resource/resource")
    assert response.json() == snapshot(
        {
            "resource": "https://example.com/resource",
            "authorization_servers": ["https://auth.example.com/authorization"],
            "scopes_supported": ["read", "write"],
            "resource_name": "Example Resource",
            "resource_documentation": "https://docs.example.com/resource",
            "bearer_methods_supported": ["header"],
        }
    )


@pytest.mark.anyio
async def test_metadata_endpoint_root_path_returns_404(test_client: httpx.AsyncClient):
    """Test that root path returns 404 for path-based resource."""

    # Root path should return 404 for path-based resources
    response = await test_client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 404


@pytest.fixture
def root_resource_app():
    """Fixture to create protected resource routes for root-level resource."""

    # Create routes for a resource without path component
    protected_resource_routes = create_protected_resource_routes(
        resource_url=AnyHttpUrl("https://example.com"),
        authorization_servers=[AnyHttpUrl("https://auth.example.com")],
        scopes_supported=["read"],
        resource_name="Root Resource",
    )

    app = Starlette(routes=protected_resource_routes)
    return app


@pytest.fixture
async def root_resource_client(root_resource_app: Starlette):
    """Fixture to create an HTTP client for the root resource app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=root_resource_app), base_url="https://mcptest.com"
    ) as client:
        yield client


@pytest.mark.anyio
async def test_metadata_endpoint_without_path(root_resource_client: httpx.AsyncClient):
    """Test metadata endpoint for root-level resource."""

    # For root resource, metadata should be at standard location
    response = await root_resource_client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    assert response.json() == snapshot(
        {
            "resource": "https://example.com/",
            "authorization_servers": ["https://auth.example.com/"],
            "scopes_supported": ["read"],
            "resource_name": "Root Resource",
            "bearer_methods_supported": ["header"],
        }
    )


class TestMetadataUrlConstruction:
    """Test URL construction utility function."""

    def test_url_without_path(self):
        """Test URL construction for resource without path component."""
        resource_url = AnyHttpUrl("https://example.com")
        result = build_resource_metadata_url(resource_url)
        assert str(result) == "https://example.com/.well-known/oauth-protected-resource"

    def test_url_with_path_component(self):
        """Test URL construction for resource with path component."""
        resource_url = AnyHttpUrl("https://example.com/mcp")
        result = build_resource_metadata_url(resource_url)
        assert str(result) == "https://example.com/.well-known/oauth-protected-resource/mcp"

    def test_url_with_trailing_slash_only(self):
        """Test URL construction for resource with trailing slash only."""
        resource_url = AnyHttpUrl("https://example.com/")
        result = build_resource_metadata_url(resource_url)
        # Trailing slash should be treated as empty path
        assert str(result) == "https://example.com/.well-known/oauth-protected-resource"

    @pytest.mark.parametrize(
        "resource_url,expected_url",
        [
            ("https://example.com", "https://example.com/.well-known/oauth-protected-resource"),
            ("https://example.com/", "https://example.com/.well-known/oauth-protected-resource"),
            ("https://example.com/mcp", "https://example.com/.well-known/oauth-protected-resource/mcp"),
            ("http://localhost:8001/mcp", "http://localhost:8001/.well-known/oauth-protected-resource/mcp"),
        ],
    )
    def test_various_resource_configurations(self, resource_url: str, expected_url: str):
        """Test URL construction with various resource configurations."""
        result = build_resource_metadata_url(AnyHttpUrl(resource_url))
        assert str(result) == expected_url


class TestRouteConsistency:
    """Test consistency between URL generation and route registration."""

    def test_route_path_matches_metadata_url(self):
        """Test that route path matches the generated metadata URL."""
        resource_url = AnyHttpUrl("https://example.com/mcp")

        # Generate metadata URL
        metadata_url = build_resource_metadata_url(resource_url)

        # Create routes
        routes = create_protected_resource_routes(
            resource_url=resource_url,
            authorization_servers=[AnyHttpUrl("https://auth.example.com")],
        )

        # Extract path from metadata URL
        from urllib.parse import urlparse

        metadata_path = urlparse(str(metadata_url)).path

        # Verify consistency
        assert len(routes) == 1
        assert routes[0].path == metadata_path

    @pytest.mark.parametrize(
        "resource_url,expected_path",
        [
            ("https://example.com", "/.well-known/oauth-protected-resource"),
            ("https://example.com/", "/.well-known/oauth-protected-resource"),
            ("https://example.com/mcp", "/.well-known/oauth-protected-resource/mcp"),
        ],
    )
    def test_consistent_paths_for_various_resources(self, resource_url: str, expected_path: str):
        """Test that URL generation and route creation are consistent."""
        resource_url_obj = AnyHttpUrl(resource_url)

        # Test URL generation
        metadata_url = build_resource_metadata_url(resource_url_obj)
        from urllib.parse import urlparse

        url_path = urlparse(str(metadata_url)).path

        # Test route creation
        routes = create_protected_resource_routes(
            resource_url=resource_url_obj,
            authorization_servers=[AnyHttpUrl("https://auth.example.com")],
        )
        route_path = routes[0].path

        # Both should match expected path
        assert url_path == expected_path
        assert route_path == expected_path
        assert url_path == route_path
