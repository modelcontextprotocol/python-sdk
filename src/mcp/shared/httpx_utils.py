"""Utilities for creating standardized httpx AsyncClient instances."""

from typing import Any

import httpx

__all__ = ["create_mcp_http_client"]


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.AsyncClient:
    """Create a standardized httpx AsyncClient with MCP defaults.

    This function provides common defaults used throughout the MCP codebase:
    - follow_redirects=True (always enabled)
    - Default timeout of 30 seconds if not specified

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx.Timeout object.
            Defaults to 30 seconds if not specified.

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
        async with create_mcp_http_client(headers) as client:
            response = await client.get("/endpoint")

        # With both custom headers and timeout
        timeout = httpx.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(headers, timeout) as client:
            response = await client.get("/long-request")
    """
    # Set MCP defaults
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
    }

    # Handle timeout
    if timeout is None:
        kwargs["timeout"] = httpx.Timeout(30.0)
    else:
        kwargs["timeout"] = timeout

    # Handle headers
    if headers is not None:
        kwargs["headers"] = headers

    return httpx.AsyncClient(**kwargs)
