"""MCP Resource Server with multi-protocol auth (OAuth-fallback discovery variant).

This variant:
- PRM does NOT include mcp_auth_protocols (only authorization_servers)
- Does NOT expose any unified discovery endpoints
- Forces clients to use OAuth fallback from PRM.authorization_servers
"""

import contextlib
import datetime
import logging
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

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp.server import FastMCP, StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.auth import AuthProtocolMetadata

from .multiprotocol import MultiProtocolAuthBackendAdapter, build_multiprotocol_backend
from .token_verifier import IntrospectionTokenVerifier

logger = logging.getLogger(__name__)


class ResourceServerSettings(BaseSettings):
    """Settings for the multi-protocol MCP Resource Server (OAuth-fallback discovery)."""

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


def create_multiprotocol_resource_server(settings: ResourceServerSettings) -> Starlette:
    """Create Starlette app with MultiProtocolAuthBackend and PRM-only (no mcp_auth_protocols, no unified discovery)."""
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
        name="MCP Resource Server (multiprotocol, OAuth-fallback discovery)",
        instructions=(
            "Resource Server with OAuth, API Key, and Mutual TLS (placeholder) auth (OAuth-fallback discovery)"
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
    # We still define full protocol metadata for logging/reference, but PRM will not include mcp_auth_protocols
    protocols_metadata = _protocol_metadata_list(settings)
    auth_protocol_ids = [p.protocol_id for p in protocols_metadata]
    protocol_prefs = _protocol_preferences_dict(settings.protocol_preferences)

    require_auth = RequireAuthMiddleware(
        streamable_app,
        required_scopes=[settings.mcp_scope],
        resource_metadata_url=resource_metadata_url,
        auth_protocols=auth_protocol_ids,
        default_protocol=settings.default_protocol,
        protocol_preferences=protocol_prefs if protocol_prefs else None,
    )

    routes: list[Route] = [
        Route(
            "/mcp",
            endpoint=require_auth,
        ),
    ]
    # PRM without mcp_auth_protocols: only authorization_servers/scopes
    routes.extend(
        create_protected_resource_routes(
            resource_url=resource_url,
            authorization_servers=[auth_settings.issuer_url],
            scopes_supported=auth_settings.required_scopes,
            # IMPORTANT: pass an explicit empty list to avoid ProtectedResourceMetadata backward-compat
            # validator auto-filling mcp_auth_protocols from authorization_servers.
            auth_protocols=[],
            default_protocol=None,
            protocol_preferences=None,
        )
    )

    # NOTE: OAuth-fallback variant intentionally does NOT add any unified discovery routes:
    # - No /.well-known/authorization_servers
    # - No /.well-known/authorization_servers/mcp

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
def main(
    port: int,
    auth_server: str,
    transport: Literal["sse", "streamable-http"],
    oauth_strict: bool,
    api_keys: str,
    dpop_enabled: bool,
) -> int:
    """Run the multi-protocol MCP Resource Server (OAuth-fallback discovery)."""
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

    app = create_multiprotocol_resource_server(settings)
    logger.info("Multi-protocol RS (OAuth-fallback discovery) running on %s", settings.server_url)
    logger.info("Auth: OAuth (introspection), API Key (X-API-Key or Bearer <key>), mTLS (placeholder)")
    if dpop_enabled:
        logger.info("DPoP: enabled (RFC 9449)")
    uvicorn.run(app, host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
