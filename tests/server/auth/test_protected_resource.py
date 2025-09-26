"""
Integration tests for MCP Oauth Protected Resource.
"""

import httpx
import pytest
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.routes import create_protected_resource_routes


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
