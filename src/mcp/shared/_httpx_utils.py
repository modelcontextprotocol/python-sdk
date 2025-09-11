"""Utilities for creating standardized httpx AsyncClient instances."""

from typing import Any, Protocol

import httpx

__all__ = ["create_mcp_http_client"]


class McpHttpClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> httpx.AsyncClient: ...


def create_mcp_http_client(**kwargs: Any) -> httpx.AsyncClient:
    """Create a standardized httpx AsyncClient with MCP defaults.

    This function provides common defaults used throughout the MCP codebase:
    - follow_redirects=True (always enabled)
    - Default timeout of 30 seconds if not specified
    - You can pass any keyword argument accepted by httpx.AsyncClient

    Args:
        Any keyword argument supported by httpx.AsyncClient (e.g. headers, timeout, auth, verify, proxies, etc).
        MCP defaults are applied unless overridden.

    Returns:
        Configured httpx.AsyncClient instance with MCP defaults.

    Note:
        The returned AsyncClient must be used as a context manager to ensure
        proper cleanup of connections.

    Examples:
        # Basic usage with MCP defaults
        async with create_mcp_http_client() as client:
            response = await client.get("https://api.example.com")

        # With custom headers
        headers = {"Authorization": "Bearer token"}
        async with create_mcp_http_client(headers=headers) as client:
            response = await client.get("/endpoint")

        # With both custom headers and timeout
        timeout = httpx.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(headers=headers, timeout=timeout) as client:
            response = await client.get("/long-request")

        # With authentication
        from httpx import BasicAuth
        auth = BasicAuth(username="user", password="pass")
        async with create_mcp_http_client(headers=headers, timeout=timeout, auth=auth) as client:
            response = await client.get("/protected-endpoint")

        # With SSL verification disabled
        async with create_mcp_http_client(verify=False) as client:
            response = await client.get("/insecure-endpoint")

        # With custom SSL context
        import ssl
        ssl_ctx = ssl.create_default_context()
        async with create_mcp_http_client(verify=ssl_ctx) as client:
            response = await client.get("/custom-endpoint")

        # With proxies and base_url
        async with create_mcp_http_client(proxies="http://proxy:8080", base_url="https://api.example.com") as client:
            response = await client.get("/resource")
    """
    # Set MCP defaults
    default_kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "timeout": httpx.Timeout(30.0),
    }
    default_kwargs.update(kwargs)
    return httpx.AsyncClient(**default_kwargs)
