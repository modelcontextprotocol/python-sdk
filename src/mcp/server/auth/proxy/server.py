# pyright: reportPrivateUsage=false, reportUnknownParameterType=false
"""Convenience helper for spinning up a FastMCP Transparent OAuth proxy server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import AnyHttpUrl

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.logging import configure_logging

from ..providers.transparent_proxy import TransparentOAuthProxyProvider

if TYPE_CHECKING:  # pragma: no cover – typing-only imports
    from mcp.server.auth.providers.transparent_proxy import _Settings as ProxySettings

__all__ = ["build_proxy_server"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_proxy_server(  # noqa: D401,E501
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    issuer_url: str | None = None,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG",
    settings: ProxySettings | None = None,
) -> FastMCP:
    """Return a fully-configured FastMCP instance running the proxy.

    Prefer passing a fully-validated *settings* object (instance of
    :class:`mcp.server.auth.providers.transparent_proxy._Settings`) which makes
    configuration explicit and type-checked.
    """

    # Runtime import to avoid circular dependency at module import time.
    from ..providers.transparent_proxy import _Settings as ProxySettings

    if settings is None:
        settings = ProxySettings.load()

    configure_logging(level=log_level)  # type: ignore[arg-type]

    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(issuer_url or f"http://localhost:{port}"),  # type: ignore[arg-type]
        resource_server_url=AnyHttpUrl(f"http://localhost:{port}"),  # type: ignore[arg-type]
        required_scopes=["openid"],
        client_registration_options=ClientRegistrationOptions(enabled=True),
    )

    provider = TransparentOAuthProxyProvider(settings=settings, auth_settings=auth_settings)  # type: ignore[arg-type]

    mcp = FastMCP(
        name="Transparent OAuth Proxy", host=host, port=port, auth_server_provider=provider, auth=auth_settings
    )

    return mcp
