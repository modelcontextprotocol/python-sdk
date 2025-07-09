# pyright: reportMissingImports=false
import argparse
import base64
import json
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv  # type: ignore
from mcp.server.auth.providers.transparent_proxy import (
    ProxySettings,  # type: ignore
    TransparentOAuthProxyProvider,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp.server import Context, FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request  # type: ignore

# Load environment variables from .env if present
load_dotenv()

# Configure logging after .env so LOG_LEVEL can come from environment
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Dedicated logger for this server module
logger = logging.getLogger("proxy_auth.combo_server")

# Suppress noisy INFO messages from the FastMCP low-level server unless we are
# explicitly running in DEBUG mode. These logs (e.g. "Processing request of type
# ListToolsRequest") are helpful for debugging but clutter normal output.

_mcp_lowlevel_logger = logging.getLogger("mcp.server.lowlevel.server")
if LOG_LEVEL == "DEBUG":
    # In full debug mode, allow the library to emit its detailed logs
    _mcp_lowlevel_logger.setLevel(logging.DEBUG)
else:
    # Otherwise, only warnings and above
    _mcp_lowlevel_logger.setLevel(logging.WARNING)

# ----------------------------------------------------------------------------
# Environment configuration
# ----------------------------------------------------------------------------
# Load and validate settings from the environment (uses .env automatically)
settings = ProxySettings.load()

# Upstream endpoints (fully-qualified URLs)
UPSTREAM_AUTHORIZE: str = str(settings.upstream_authorize)
UPSTREAM_TOKEN: str = str(settings.upstream_token)
UPSTREAM_JWKS_URI = settings.jwks_uri
# Derive base URL from the authorize endpoint for convenience / tests
UPSTREAM_BASE: str = UPSTREAM_AUTHORIZE.rsplit("/", 1)[0]

# Client credentials & defaults
CLIENT_ID: str = settings.client_id or "demo-client-id"
CLIENT_SECRET = settings.client_secret
DEFAULT_SCOPE: str = settings.default_scope

# Metadata URL (only used if we need to fetch from upstream)
UPSTREAM_METADATA = f"{UPSTREAM_BASE}/.well-known/oauth-authorization-server"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _mask_secret(secret: str | None) -> str | None:  # noqa: D401
    """Return a masked version of the given secret.

    The first and last four characters are preserved (if available) and the
    middle section is replaced by asterisks. If the secret is shorter than
    eight characters, the entire value is replaced by ``*``.
    """

    if not secret:
        return None

    if len(secret) <= 8:
        return "*" * len(secret)

    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


# Consolidated configuration (with sensitive data redacted)
_masked_settings = settings.model_dump(exclude_none=True).copy()

if "client_secret" in _masked_settings:
    _masked_settings["client_secret"] = _mask_secret(_masked_settings["client_secret"])

# Log configuration at *debug* level only so it can be enabled when needed
logger.debug("[Proxy Config] %s", _masked_settings)

# Server host/port
COMBO_SERVER_PORT = int(os.getenv("COMBO_SERVER_PORT", os.getenv("PROXY_PORT", "8000")))
COMBO_SERVER_HOST = os.getenv("COMBO_SERVER_HOST", os.getenv("PROXY_HOST", "localhost"))
# Infer PROXY_ISSUER_URL from COMBO_SERVER_HOST and COMBO_SERVER_PORT
# if not explicitly set
PROXY_ISSUER_URL = (
    os.getenv("PROXY_ISSUER_URL") or f"http://{COMBO_SERVER_HOST}:{COMBO_SERVER_PORT}"
)

# ----------------------------------------------------------------------------
# FastMCP server (now created via library helper)
# ----------------------------------------------------------------------------
auth_settings = AuthSettings(
    issuer_url=AnyHttpUrl(PROXY_ISSUER_URL),  # type: ignore[arg-type]
    resource_server_url=AnyHttpUrl(PROXY_ISSUER_URL),  # type: ignore[arg-type]
    required_scopes=["openid"],
    client_registration_options=ClientRegistrationOptions(enabled=True),
)


def create_combo_server(host: str = COMBO_SERVER_HOST, port: int = COMBO_SERVER_PORT):
    """Create a combined proxy server instance with the given configuration."""

    # Create the OAuth provider with our settings
    oauth_provider = TransparentOAuthProxyProvider(
        settings=settings, auth_settings=auth_settings
    )

    # Create FastMCP instance with the provider
    server = FastMCP(
        name="Transparent OAuth Proxy",
        host=host,
        port=port,
        auth_server_provider=oauth_provider,
        auth=auth_settings,
    )

    # Add demo tools
    @server.tool()
    def echo(message: str) -> str:
        return f"Echo: {message}"

    @server.tool()
    async def user_info(ctx: Context[Any, Any, Request]) -> dict[str, Any]:
        """
        Get information about the authenticated user.

        This tool demonstrates accessing user information from the OAuth access token.
        The user must be authenticated via OAuth to access this tool.

        Returns:
            Dictionary containing user information from the access token
        """
        from mcp.server.auth.middleware.auth_context import get_access_token

        # Get the access token from the authentication context
        access_token = get_access_token()

        if not access_token:
            return {
                "error": "No access token found - user not authenticated",
                "authenticated": False,
            }

        # Attempt to decode the access token as JWT to extract useful user claims.
        # Many OAuth providers issue JWT access tokens (or ID tokens) that contain
        # the user's subject (sub) and preferred username. We parse the token
        # *without* signature verification – we only need the public claims for
        # display purposes. If the token is opaque or the decode fails, we simply
        # skip this step.

        def _try_decode_jwt(token_str: str) -> dict[str, Any] | None:  # noqa: D401
            """Best-effort JWT decode without verification.

            Returns the payload dictionary if the token *looks* like a JWT and can
            be base64-decoded. If anything fails we return None.
            """

            try:
                parts = token_str.split(".")
                if len(parts) != 3:
                    return None  # Not a JWT

                # JWT parts are URL-safe base64 without padding
                def _b64decode(segment: str) -> bytes:
                    padding = "=" * (-len(segment) % 4)
                    return base64.urlsafe_b64decode(segment + padding)

                payload_bytes = _b64decode(parts[1])
                return json.loads(payload_bytes)
            except Exception:  # noqa: BLE001
                return None

        jwt_claims = _try_decode_jwt(access_token.token)

        # Build response with token information plus any extracted claims
        response: dict[str, Any] = {
            "authenticated": True,
            "client_id": access_token.client_id,
            "scopes": access_token.scopes,
            "token_type": "Bearer",
            "expires_at": access_token.expires_at,
            "resource": access_token.resource,
        }

        if jwt_claims:
            # Prefer the `userid` claim used in FastMCP examples; fall back to `sub` if
            # absent.
            uid = jwt_claims.get("userid") or jwt_claims.get("sub")
            if uid is not None:
                response["userid"] = uid  # camelCase variant used in FastMCP reference
                response["user_id"] = uid  # snake_case variant
            response["username"] = (
                jwt_claims.get("preferred_username")
                or jwt_claims.get("nickname")
                or jwt_claims.get("name")
            )
            response["issuer"] = jwt_claims.get("iss")
            response["audience"] = jwt_claims.get("aud")
            response["issued_at"] = jwt_claims.get("iat")

        # Calculate expiration helpers
        if access_token.expires_at:
            response["expires_at_iso"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(access_token.expires_at)
            )
            response["expires_in_seconds"] = max(
                0, access_token.expires_at - int(time.time())
            )

        return response

    @server.tool()
    async def test_endpoint(
        message: str = "Hello from proxy server!",
    ) -> dict[str, Any]:
        """
        Test endpoint for debugging OAuth proxy functionality.

        Args:
            message: Optional message to echo back

        Returns:
            Test response with server information
        """
        return {
            "message": message,
            "server": "Transparent OAuth Proxy Server",
            "status": "active",
            "oauth_configured": True,
        }

    return server


# Create a default server instance
combo_server = create_combo_server()


def main():
    """Command-line entry point for the Combo Server."""
    parser = argparse.ArgumentParser(description="MCP OAuth Proxy Combo Server")
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (overrides COMBO_SERVER_HOST env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (overrides COMBO_SERVER_PORT env var)",
    )
    parser.add_argument(
        "--transport",
        default="streamable-http",
        help="Transport type (streamable-http or websocket)",
    )

    args = parser.parse_args()

    # Use command-line arguments only if provided, otherwise use environment variables
    host = args.host or COMBO_SERVER_HOST
    port = args.port or COMBO_SERVER_PORT

    # Log the configuration being used
    logger.info(f"Starting Combo Server with host={host}, port={port}")

    # Create a server with the specified configuration
    combo_server = create_combo_server(host=host, port=port)

    logger.info(f"🚀 MCP OAuth Proxy Combo Server running on http://{host}:{port}")
    combo_server.run(transport=args.transport)


if __name__ == "__main__":
    main()
