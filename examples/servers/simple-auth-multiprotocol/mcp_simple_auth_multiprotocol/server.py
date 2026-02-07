"""MCP Resource Server with multi-protocol auth (OAuth, API Key, Mutual TLS placeholder).

Uses MultiProtocolAuthBackend, PRM with auth_protocols, and /.well-known/authorization_servers.

Supports multiple discovery variants via VariantConfig for testing different client
discovery paths.  The default entry point (``main``) uses the "full" variant which
exposes PRM *with* ``mcp_auth_protocols`` and root unified discovery.  Other variants
are available as preset constants and consumed by the thin shim packages
(``mcp_simple_auth_multiprotocol_prm_only``, etc.).
"""

import contextlib
import datetime
import logging
from dataclasses import dataclass
from typing import Any, Literal

import click
import uvicorn
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route
from starlette.types import ASGIApp

from mcp.server.auth.handlers.discovery import AuthorizationServersDiscoveryHandler
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_authorization_servers_discovery_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp.server import FastMCP, StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.auth import AuthProtocolMetadata

from .multiprotocol import MultiProtocolAuthBackendAdapter, build_multiprotocol_backend
from .token_verifier import IntrospectionTokenVerifier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Variant configuration
#
# Each variant controls which discovery endpoints the server exposes.
# This allows testing every client discovery path with a single codebase.
#
#   Variant          PRM mcp_auth_protocols   root discovery   path discovery
#   full (default)   yes                      yes              no
#   prm_only         yes                      no               no
#   path_only        no                       no               yes
#   root_only        no                       yes              no
#   oauth_fallback   no                       no               no
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VariantConfig:
    """Controls PRM content and discovery route exposure for each server variant."""

    name: str
    prm_includes_auth_protocols: bool
    expose_root_discovery: bool
    expose_path_discovery: bool
    www_auth_include_protocol_hints: bool


VARIANT_FULL = VariantConfig(
    name="full",
    prm_includes_auth_protocols=True,
    expose_root_discovery=True,
    expose_path_discovery=False,
    www_auth_include_protocol_hints=True,
)
VARIANT_PRM_ONLY = VariantConfig(
    name="prm_only",
    prm_includes_auth_protocols=True,
    expose_root_discovery=False,
    expose_path_discovery=False,
    www_auth_include_protocol_hints=False,
)
VARIANT_PATH_ONLY = VariantConfig(
    name="path_only",
    prm_includes_auth_protocols=False,
    expose_root_discovery=False,
    expose_path_discovery=True,
    www_auth_include_protocol_hints=False,
)
VARIANT_ROOT_ONLY = VariantConfig(
    name="root_only",
    prm_includes_auth_protocols=False,
    expose_root_discovery=True,
    expose_path_discovery=False,
    www_auth_include_protocol_hints=False,
)
VARIANT_OAUTH_FALLBACK = VariantConfig(
    name="oauth_fallback",
    prm_includes_auth_protocols=False,
    expose_root_discovery=False,
    expose_path_discovery=False,
    www_auth_include_protocol_hints=False,
)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class ResourceServerSettings(BaseSettings):
    """Settings for the multi-protocol MCP Resource Server."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESOURCE_")

    host: str = "localhost"
    port: int = 8002
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8002/mcp")
    auth_server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    auth_server_introspection_endpoint: str = "http://localhost:9000/introspect"
    mcp_scope: str = "user"
    oauth_strict: bool = False
    api_key_valid_keys: str = "demo-api-key-12345"
    default_protocol: str = "oauth2"
    protocol_preferences: str = "oauth2:1,api_key:2,mutual_tls:3"
    dpop_enabled: bool = False


def _protocol_metadata_list(settings: ResourceServerSettings) -> list[AuthProtocolMetadata]:
    """Build AuthProtocolMetadata for oauth2, api_key, mutual_tls."""
    auth_base = str(settings.auth_server_url).rstrip("/")
    oauth_metadata_url = AnyHttpUrl(f"{auth_base}/.well-known/oauth-authorization-server")
    return [
        AuthProtocolMetadata(
            protocol_id="oauth2",
            protocol_version="2.0",
            metadata_url=oauth_metadata_url,
            scopes_supported=[settings.mcp_scope],
        ),
        AuthProtocolMetadata(protocol_id="api_key", protocol_version="1.0"),
        AuthProtocolMetadata(protocol_id="mutual_tls", protocol_version="1.0"),
    ]


def _protocol_preferences_dict(prefs_str: str) -> dict[str, int]:
    """Parse protocol_preferences string like 'oauth2:1,api_key:2,mutual_tls:3'."""
    out: dict[str, int] = {}
    for part in prefs_str.split(","):
        s = part.strip()
        if ":" in s:
            proto, prio = s.split(":", 1)
            try:
                out[proto.strip()] = int(prio.strip())
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------
# Variant helpers: PRM and discovery route injection
# ---------------------------------------------------------------------------


def _add_prm_routes(
    routes: list[Route],
    resource_url: AnyHttpUrl,
    auth_settings: AuthSettings,
    protocols_metadata: list[AuthProtocolMetadata],
    settings: ResourceServerSettings,
    variant: VariantConfig,
) -> None:
    """Add Protected Resource Metadata routes.

    When the variant advertises protocols via PRM, ``mcp_auth_protocols``,
    ``default_protocol``, and ``protocol_preferences`` are included.
    Otherwise only RFC 9728 ``authorization_servers`` / ``scopes`` are served.
    """
    protocol_prefs = _protocol_preferences_dict(settings.protocol_preferences) or None
    if variant.prm_includes_auth_protocols:
        routes.extend(
            create_protected_resource_routes(
                resource_url=resource_url,
                authorization_servers=[auth_settings.issuer_url],
                scopes_supported=auth_settings.required_scopes,
                auth_protocols=protocols_metadata,
                default_protocol=settings.default_protocol,
                protocol_preferences=protocol_prefs,
            )
        )
    else:
        # Explicit empty list so the PRM JSON includes "mcp_auth_protocols": []
        # rather than omitting the field — signals "no protocols via PRM".
        routes.extend(
            create_protected_resource_routes(
                resource_url=resource_url,
                authorization_servers=[auth_settings.issuer_url],
                scopes_supported=auth_settings.required_scopes,
                auth_protocols=[],
                default_protocol=None,
                protocol_preferences=None,
            )
        )


def _add_discovery_routes(
    routes: list[Route],
    protocols_metadata: list[AuthProtocolMetadata],
    settings: ResourceServerSettings,
    variant: VariantConfig,
) -> None:
    """Add unified discovery routes (root, path-relative, or none) based on variant."""
    protocol_prefs = _protocol_preferences_dict(settings.protocol_preferences) or None
    if variant.expose_root_discovery:
        routes.extend(
            create_authorization_servers_discovery_routes(
                protocols=protocols_metadata,
                default_protocol=settings.default_protocol,
                protocol_preferences=protocol_prefs,
            )
        )
    if variant.expose_path_discovery:
        handler = AuthorizationServersDiscoveryHandler(
            protocols=protocols_metadata,
            default_protocol=settings.default_protocol,
            protocol_preferences=protocol_prefs,
        )
        routes.append(
            Route(
                "/.well-known/authorization_servers/mcp",
                endpoint=handler.handle,
                methods=["GET", "OPTIONS"],
            )
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_multiprotocol_resource_server(
    settings: ResourceServerSettings,
    variant: VariantConfig = VARIANT_FULL,
) -> Starlette:
    """Create Starlette app with MultiProtocolAuthBackend, PRM, and discovery routes."""
    oauth_verifier = IntrospectionTokenVerifier(
        introspection_endpoint=settings.auth_server_introspection_endpoint,
        server_url=str(settings.server_url),
        validate_resource=settings.oauth_strict,
    )
    api_key_keys = {k.strip() for k in settings.api_key_valid_keys.split(",") if k.strip()}
    backend, dpop_verifier = build_multiprotocol_backend(
        oauth_verifier,
        api_key_keys,
        api_key_scopes=[settings.mcp_scope],
        dpop_enabled=settings.dpop_enabled,
    )
    adapter = MultiProtocolAuthBackendAdapter(backend, dpop_verifier=dpop_verifier)

    fastmcp = FastMCP(
        name=f"MCP Resource Server (multiprotocol, {variant.name})",
        instructions=(
            f"Resource Server with OAuth, API Key, and Mutual TLS (placeholder) auth ({variant.name} discovery)"
        ),
        host=settings.host,
        port=settings.port,
        auth=None,
    )

    @fastmcp.tool()
    async def get_time() -> dict[str, Any]:
        """Return current server time (requires auth)."""
        now = datetime.datetime.now()
        return {
            "current_time": now.isoformat(),
            "timezone": "UTC",
            "timestamp": now.timestamp(),
            "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    mcp_server = getattr(fastmcp, "_mcp_server")
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        retry_interval=None,
        json_response=False,
        stateless=False,
        security_settings=None,
    )
    streamable_app: ASGIApp = StreamableHTTPASGIApp(session_manager)

    auth_settings = AuthSettings(
        issuer_url=settings.auth_server_url,
        required_scopes=[settings.mcp_scope],
        resource_server_url=settings.server_url,
    )
    resource_url = auth_settings.resource_server_url
    assert resource_url is not None
    resource_metadata_url = build_resource_metadata_url(resource_url)
    protocols_metadata = _protocol_metadata_list(settings)
    auth_protocol_ids = [p.protocol_id for p in protocols_metadata]
    protocol_prefs = _protocol_preferences_dict(settings.protocol_preferences) or None
    www_auth_protocol_ids = auth_protocol_ids if variant.www_auth_include_protocol_hints else None
    www_auth_default_protocol = settings.default_protocol if variant.www_auth_include_protocol_hints else None
    www_auth_protocol_prefs = protocol_prefs if variant.www_auth_include_protocol_hints else None

    require_auth = RequireAuthMiddleware(
        streamable_app,
        required_scopes=[settings.mcp_scope],
        resource_metadata_url=resource_metadata_url,
        auth_protocols=www_auth_protocol_ids,
        default_protocol=www_auth_default_protocol,
        protocol_preferences=www_auth_protocol_prefs,
    )

    routes: list[Route] = [
        Route("/mcp", endpoint=require_auth),
    ]
    _add_prm_routes(routes, resource_url, auth_settings, protocols_metadata, settings, variant)
    _add_discovery_routes(routes, protocols_metadata, settings, variant)

    middleware = [
        Middleware(AuthenticationMiddleware, backend=adapter),
        Middleware(AuthContextMiddleware),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with session_manager.run():
            yield

    return Starlette(
        debug=True,
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
    )


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def main_for_variant(variant: VariantConfig) -> click.Command:
    """Create a click CLI command for a specific discovery variant.

    Used by the default entry point (``main``) and by the thin shim packages
    (e.g. ``mcp_simple_auth_multiprotocol_prm_only.server``).
    """

    @click.command()
    @click.option("--port", default=8002, help="Port to listen on")
    @click.option("--auth-server", default="http://localhost:9000", help="Authorization Server URL")
    @click.option(
        "--transport",
        default="streamable-http",
        type=click.Choice(["sse", "streamable-http"]),
        help="Transport protocol",
    )
    @click.option("--oauth-strict", is_flag=True, help="Enable RFC 8707 resource validation")
    @click.option("--api-keys", default="demo-api-key-12345", help="Comma-separated valid API keys")
    @click.option("--dpop-enabled", is_flag=True, help="Enable DPoP proof verification (RFC 9449)")
    def cli(
        port: int,
        auth_server: str,
        transport: Literal["sse", "streamable-http"],
        oauth_strict: bool,
        api_keys: str,
        dpop_enabled: bool,
    ) -> int:
        """Run the multi-protocol MCP Resource Server."""
        logging.basicConfig(level=logging.INFO)
        try:
            host = "localhost"
            server_url = f"http://{host}:{port}/mcp"
            settings = ResourceServerSettings(
                host=host,
                port=port,
                server_url=AnyHttpUrl(server_url),
                auth_server_url=AnyHttpUrl(auth_server),
                auth_server_introspection_endpoint=f"{auth_server}/introspect",
                oauth_strict=oauth_strict,
                api_key_valid_keys=api_keys,
                dpop_enabled=dpop_enabled,
            )
        except ValueError as e:
            logger.error("Configuration error: %s", e)
            return 1

        app = create_multiprotocol_resource_server(settings, variant)
        logger.info("Multi-protocol RS (%s) running on %s", variant.name, settings.server_url)
        logger.info("Auth: OAuth (introspection), API Key (X-API-Key or Bearer <key>), mTLS (placeholder)")
        if settings.dpop_enabled:
            logger.info("DPoP: enabled (RFC 9449)")
        uvicorn.run(app, host=settings.host, port=settings.port)
        return 0

    return cli


# Default entry point: full variant (PRM + root discovery)
main = main_for_variant(VARIANT_FULL)


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
