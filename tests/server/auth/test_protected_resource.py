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
async def test_metadata_endpoint(test_client: httpx.AsyncClient):
    """Test the OAuth 2.0 Protected Resource metadata endpoint."""

    response = await test_client.get("/.well-known/oauth-protected-resource")
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
