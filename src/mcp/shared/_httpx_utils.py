"""Utilities for creating standardized httpx AsyncClient instances."""

from typing import Any, Protocol

import httpx

__all__ = ["create_mcp_http_client", "MCP_DEFAULT_TIMEOUT", "MCP_DEFAULT_SSE_READ_TIMEOUT"]

MCP_DEFAULT_TIMEOUT = 30.0  # seconds, general operations
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # seconds, long-lived SSE streams


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient: ...


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an httpx AsyncClient with MCP defaults.

    Enables follow_redirects and, when `timeout` is omitted, defaults to 30s for
    connect/write/pool and 300s for read so long-lived SSE streams stay open.
    Use the returned client as a context manager to clean up connections.
    """
    kwargs: dict[str, Any] = {"follow_redirects": True}

    if timeout is None:
        kwargs["timeout"] = httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    else:
        kwargs["timeout"] = timeout

    if headers is not None:
        kwargs["headers"] = headers

    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth

    return httpx.AsyncClient(**kwargs)
