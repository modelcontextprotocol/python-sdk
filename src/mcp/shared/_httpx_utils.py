"""Utilities for creating standardized httpx2 AsyncClient instances."""

from typing import Any, Protocol

import httpx2

__all__ = ["create_mcp_http_client", "MCP_DEFAULT_TIMEOUT", "MCP_DEFAULT_SSE_READ_TIMEOUT"]

# Default MCP timeout configuration
MCP_DEFAULT_TIMEOUT = 30.0  # General operations (seconds)
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # SSE streams - 5 minutes (seconds)


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient: ...


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
) -> httpx2.AsyncClient:
    """Create a standardized httpx2 AsyncClient with MCP defaults.

    Always enables follow_redirects and applies an SSE-friendly default timeout.

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx2.Timeout object. Defaults to 30s for
            connect/write/pool and 300s for read (for long-lived SSE streams).
        auth: Optional authentication handler.

    Returns:
        Configured httpx2.AsyncClient instance with MCP defaults.

    Note:
        The returned AsyncClient must be used as a context manager to ensure
        proper cleanup of connections.

    Example:
        Basic usage with MCP defaults:

        ```python
        async with create_mcp_http_client() as client:
            response = await client.get("https://api.example.com")
        ```

        With custom headers:

        ```python
        headers = {"Authorization": "Bearer token"}
        async with create_mcp_http_client(headers) as client:
            response = await client.get("/endpoint")
        ```

        With both custom headers and timeout:

        ```python
        timeout = httpx2.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(headers, timeout) as client:
            response = await client.get("/long-request")
        ```

        With authentication:

        ```python
        from httpx2 import BasicAuth
        auth = BasicAuth(username="user", password="pass")
        async with create_mcp_http_client(headers, timeout, auth) as client:
            response = await client.get("/protected-endpoint")
        ```
    """
    # Set MCP defaults
    kwargs: dict[str, Any] = {"follow_redirects": True}

    # Handle timeout
    if timeout is None:
        kwargs["timeout"] = httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    else:
        kwargs["timeout"] = timeout

    # Handle headers
    if headers is not None:
        kwargs["headers"] = headers

    # Handle authentication
    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth

    return httpx2.AsyncClient(**kwargs)
