# pyright: reportGeneralTypeIssues=false
"""Starlette routes that implement the transparent OAuth proxy endpoints."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import httpx  # type: ignore
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp.server.fastmcp.utilities.logging import configure_logging

__all__ = ["fetch_upstream_metadata", "create_proxy_routes"]

logger = logging.getLogger("transparent_oauth_proxy.routes")


# ---------------------------------------------------------------------------
# Helper – fetch (or synthesise) upstream AS metadata
# ---------------------------------------------------------------------------


async def fetch_upstream_metadata(  # noqa: D401
    upstream_base: str,
    upstream_authorize: str,
    upstream_token: str,
    upstream_jwks_uri: str | None = None,
) -> dict[str, Any]:
    """Return upstream metadata, mirroring logic from old server.py."""

    # If explicit endpoints provided, craft a synthetic metadata object.
    if upstream_authorize and upstream_token:
        return {
            "issuer": upstream_base,
            "authorization_endpoint": upstream_authorize,
            "token_endpoint": upstream_token,
            "registration_endpoint": "/register",
            "jwks_uri": upstream_jwks_uri or "",
        }

    # Otherwise attempt remote fetch.
    metadata_url = f"{upstream_base}/.well-known/oauth-authorization-server"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(metadata_url, timeout=10)
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch upstream metadata (%s); using fallback.", exc)
        return {
            "issuer": "fallback",
            "authorization_endpoint": "/authorize",
            "token_endpoint": "/token",
            "registration_endpoint": "/register",
        }


# ---------------------------------------------------------------------------
# Route factory – returns Starlette Route objects
# ---------------------------------------------------------------------------


def create_proxy_routes(provider: Any) -> list[Route]:  # type: ignore[valid-type]
    """Create all additional proxy-specific routes.

    The *provider* must be an instance of
    `TransparentOAuthProxyProvider` (duck-typed here to avoid circular imports).
    """

    configure_logging()  # ensure log format if not already set

    s = provider._s  # access its validated settings (_Settings)

    # Introduce a dedicated handler class to avoid nested closures while still
    # retaining the convenience of accessing validated settings via
    # ``self.s``.  This improves introspection, simplifies debugging and makes
    # future extensibility (e.g. dependency injection) easier.

    class _ProxyHandlers:  # noqa: D401,E501
        """Collection of async endpoints implementing the proxy logic."""

        def __init__(self, settings: Any):  # type: ignore[valid-type]
            self.s = settings

        # ------------------------------------------------------------------
        # /.well-known/oauth-authorization-server
        # ------------------------------------------------------------------
        async def metadata(self, request: Request) -> Response:  # noqa: D401
            logger.info("🔍 /.well-known/oauth-authorization-server endpoint accessed")

            data = await fetch_upstream_metadata(
                self.s.upstream_authorize.rsplit("/", 1)[0],  # base
                str(self.s.upstream_authorize),
                str(self.s.upstream_token),
                self.s.jwks_uri,
            )

            host = request.headers.get("host", "localhost")
            scheme = "https" if request.url.scheme == "https" else "http"
            issuer = f"{scheme}://{host}"
            data.update(
                {
                    "issuer": issuer,
                    "authorization_endpoint": f"{issuer}/authorize",
                    "token_endpoint": f"{issuer}/token",
                    "registration_endpoint": f"{issuer}/register",
                }
            )
            return JSONResponse(data)

        # ------------------------------------------------------------------
        # /register – Dynamic Client Registration stub
        # ------------------------------------------------------------------
        async def register(self, request: Request) -> Response:  # noqa: D401
            body = await request.json()
            client_metadata = {
                "client_id": self.s.client_id,
                "client_secret": self.s.client_secret,
                "token_endpoint_auth_method": "client_secret_post" if self.s.client_secret else "none",
                **body,
            }
            return JSONResponse(client_metadata, status_code=201)

        # ------------------------------------------------------------------
        # /authorize – Redirect to upstream with injections
        # ------------------------------------------------------------------
        async def authorize(self, request: Request) -> Response:  # noqa: D401
            params = dict(request.query_params)
            params["client_id"] = self.s.client_id
            if "scope" not in params:
                params["scope"] = self.s.default_scope

            redirect_url = f"{self.s.upstream_authorize}?{urllib.parse.urlencode(params)}"
            return RedirectResponse(redirect_url)

        # ------------------------------------------------------------------
        # /revoke – Pass-through
        # ------------------------------------------------------------------
        async def revoke(self, request: Request) -> Response:  # noqa: D401
            form = await request.form()
            data = dict(form)
            data.setdefault("client_id", self.s.client_id)
            if self.s.client_secret:
                data.setdefault("client_secret", self.s.client_secret)

            async with httpx.AsyncClient() as client:
                r = await client.post(str(self.s.upstream_token).rsplit("/", 1)[0] + "/revoke", data=data, timeout=10)
                return JSONResponse(r.json(), status_code=r.status_code)

    handlers = _ProxyHandlers(s)

    return [
        Route("/.well-known/oauth-authorization-server", handlers.metadata, methods=["GET"]),
        Route("/register", handlers.register, methods=["POST"]),
        Route("/authorize", handlers.authorize, methods=["GET"]),
        Route("/revoke", handlers.revoke, methods=["POST"]),
    ]
