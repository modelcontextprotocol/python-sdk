"""Utilities for creating standardized httpx AsyncClient instances."""

from __future__ import annotations

from typing import Any

import httpx

__all__ = ["create_mcp_http_client"]


def create_mcp_http_client(
    *,
    headers: dict[str, Any] | None = None,
    timeout: httpx.Timeout | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Create a standardized httpx AsyncClient with MCP defaults.

    This function provides common defaults used throughout the MCP codebase:
    - follow_redirects=True (always enabled)
    - Default timeout of 30 seconds if not specified
    - Headers will be merged with any existing headers in kwargs

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx.Timeout object.
            Defaults to 30 seconds if not specified.
        **kwargs: Additional keyword arguments to pass to AsyncClient.

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

        # With custom timeout
        timeout = httpx.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(timeout=timeout) as client:
            response = await client.get("/long-request")
    """
    # Set MCP defaults
    defaults: dict[str, Any] = {
        "follow_redirects": True,
    }

    # Handle timeout
    if timeout is None:
        defaults["timeout"] = httpx.Timeout(30.0)
    else:
        defaults["timeout"] = timeout

    # Handle headers with proper merging
    if headers is not None:
        existing_headers = kwargs.get("headers", {})
        merged_headers = {**existing_headers, **headers}
        kwargs["headers"] = merged_headers

    # Merge kwargs with defaults (defaults take precedence)
    kwargs = {**kwargs, **defaults}

    return httpx.AsyncClient(**kwargs)
