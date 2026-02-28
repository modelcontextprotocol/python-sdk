"""Utilities for creating standardized httpx AsyncClient instances."""

import logging
from enum import Enum
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "MCP_DEFAULT_SSE_READ_TIMEOUT",
    "MCP_DEFAULT_TIMEOUT",
    "RedirectPolicy",
    "create_mcp_http_client",
]

# Default MCP timeout configuration
MCP_DEFAULT_TIMEOUT = 30.0  # General operations (seconds)
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # SSE streams - 5 minutes (seconds)


class RedirectPolicy(Enum):
    """Policy for validating HTTP redirects to protect against SSRF attacks.

    Attributes:
        ALLOW_ALL: No restrictions on redirects (legacy behavior).
        BLOCK_SCHEME_DOWNGRADE: Block HTTPS-to-HTTP downgrades on redirect (default).
        ENFORCE_HTTPS: Only allow HTTPS redirect destinations.
    """

    ALLOW_ALL = "allow_all"
    BLOCK_SCHEME_DOWNGRADE = "block_scheme_downgrade"
    ENFORCE_HTTPS = "enforce_https"


async def _check_redirect(response: httpx.Response, policy: RedirectPolicy) -> None:
    """Validate redirect responses against the configured policy.

    This is installed as an httpx response event hook. It inspects redirect
    responses (3xx with a ``next_request``) and raises
    :class:`httpx.HTTPStatusError` when the redirect violates *policy*.

    Args:
        response: The httpx response to check.
        policy: The redirect policy to enforce.
    """
    if not response.is_redirect or response.next_request is None:
        return

    original_url = response.request.url
    redirect_url = response.next_request.url

    if policy == RedirectPolicy.BLOCK_SCHEME_DOWNGRADE:
        if original_url.scheme == "https" and redirect_url.scheme == "http":
            logger.warning(
                "Blocked HTTPS-to-HTTP redirect from %s to %s",
                original_url,
                redirect_url,
            )
            raise httpx.HTTPStatusError(
                f"HTTPS-to-HTTP redirect blocked: {original_url} -> {redirect_url}",
                request=response.request,
                response=response,
            )
    elif policy == RedirectPolicy.ENFORCE_HTTPS:
        if redirect_url.scheme != "https":
            logger.warning(
                "Blocked non-HTTPS redirect from %s to %s",
                original_url,
                redirect_url,
            )
            raise httpx.HTTPStatusError(
                f"Non-HTTPS redirect blocked: {original_url} -> {redirect_url}",
                request=response.request,
                response=response,
            )


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        redirect_policy: RedirectPolicy = RedirectPolicy.BLOCK_SCHEME_DOWNGRADE,
    ) -> httpx.AsyncClient: ...


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    redirect_policy: RedirectPolicy = RedirectPolicy.BLOCK_SCHEME_DOWNGRADE,
) -> httpx.AsyncClient:
    """Create a standardized httpx AsyncClient with MCP defaults.

    This function provides common defaults used throughout the MCP codebase:
    - follow_redirects=True (always enabled)
    - Default timeout of 30 seconds if not specified
    - SSRF redirect protection via *redirect_policy*

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx.Timeout object.
            Defaults to 30 seconds if not specified.
        auth: Optional authentication handler.
        redirect_policy: Policy controlling which redirects are allowed.
            Defaults to ``RedirectPolicy.BLOCK_SCHEME_DOWNGRADE`` which blocks
            HTTPS-to-HTTP downgrades.  Use ``RedirectPolicy.ENFORCE_HTTPS`` to
            only allow HTTPS destinations, or ``RedirectPolicy.ALLOW_ALL`` to
            disable redirect validation entirely (legacy behavior).

    Returns:
        Configured httpx.AsyncClient instance with MCP defaults.

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
        timeout = httpx.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(headers, timeout) as client:
            response = await client.get("/long-request")
        ```

        With authentication:

        ```python
        from httpx import BasicAuth
        auth = BasicAuth(username="user", password="pass")
        async with create_mcp_http_client(headers, timeout, auth) as client:
            response = await client.get("/protected-endpoint")
        ```
    """
    # Set MCP defaults
    kwargs: dict[str, Any] = {"follow_redirects": True}

    # Handle timeout
    if timeout is None:
        kwargs["timeout"] = httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    else:
        kwargs["timeout"] = timeout

    # Handle headers
    if headers is not None:
        kwargs["headers"] = headers

    # Handle authentication
    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth

    # Install redirect validation hook
    if redirect_policy != RedirectPolicy.ALLOW_ALL:

        async def check_redirect_hook(response: httpx.Response) -> None:
            await _check_redirect(response, redirect_policy)

        kwargs["event_hooks"] = {"response": [check_redirect_hook]}

    return httpx.AsyncClient(**kwargs)
