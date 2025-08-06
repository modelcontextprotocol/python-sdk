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
def protected_resource_app():
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
async def protected_resource_test_client(protected_resource_app: Starlette):
    """Fixture to create an HTTP client for the protected resource app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=protected_resource_app), base_url="https://mcptest.com"
    ) as client:
        yield client


class TestProtectedResourceMetadata:
    """Test the Protected Resource Metadata model."""

    @pytest.mark.anyio
    async def test_metadata_endpoint(self, protected_resource_test_client: httpx.AsyncClient):
        """Test the OAuth 2.0 Protected Resource metadata endpoint."""

        response = await protected_resource_test_client.get("/.well-known/oauth-protected-resource")
        metadata = response.json()
        assert metadata == snapshot(
            {
                "resource": "https://example.com/resource",
                "authorization_servers": ["https://auth.example.com/authorization"],
                "scopes_supported": ["read", "write"],
                "resource_name": "Example Resource",
                "resource_documentation": "https://docs.example.com/resource",
                "bearer_methods_supported": ["header"],
            }
        )
