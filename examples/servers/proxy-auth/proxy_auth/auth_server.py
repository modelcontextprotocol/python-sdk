# pyright: reportMissingImports=false
import argparse
import logging
import os

from dotenv import load_dotenv  # type: ignore
from mcp.server.auth.providers.transparent_proxy import (
    ProxySettings,  # type: ignore
    TransparentOAuthProxyProvider,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp.server import FastMCP
from pydantic import AnyHttpUrl

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
logger = logging.getLogger("proxy_auth.auth_server")

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

## Load and validate settings from the environment (uses .env automatically)
settings = ProxySettings.load()

# Server host/port
RESOURCE_SERVER_PORT = int(os.getenv("RESOURCE_SERVER_PORT", "8000"))
RESOURCE_SERVER_HOST = os.getenv("RESOURCE_SERVER_HOST", "localhost")
RESOURCE_SERVER_URL = os.getenv(
    "RESOURCE_SERVER_URL", f"http://{RESOURCE_SERVER_HOST}:{RESOURCE_SERVER_PORT}"
)

# Auth server configuration
AUTH_SERVER_PORT = int(os.getenv("AUTH_SERVER_PORT", "9000"))
AUTH_SERVER_HOST = os.getenv("AUTH_SERVER_HOST", "localhost")
AUTH_SERVER_URL = os.getenv(
    "AUTH_SERVER_URL", f"http://{AUTH_SERVER_HOST}:{AUTH_SERVER_PORT}"
)

auth_settings = AuthSettings(
    issuer_url=AnyHttpUrl(AUTH_SERVER_URL),
    resource_server_url=AnyHttpUrl(RESOURCE_SERVER_URL),
    required_scopes=["openid"],
)

# Create the OAuth provider with our settings
oauth_provider = TransparentOAuthProxyProvider(
    settings=settings, auth_settings=auth_settings
)


# ----------------------------------------------------------------------------
# Auth Server using FastMCP
# ----------------------------------------------------------------------------
def create_auth_server(
    host: str = AUTH_SERVER_HOST,
    port: int = AUTH_SERVER_PORT,
    auth_settings: AuthSettings = auth_settings,
    oauth_provider: TransparentOAuthProxyProvider = oauth_provider,
):
    """Create a auth server instance with the given configuration."""

    # Create FastMCP resource server instance
    auth_server = FastMCP(
        name="Auth Server",
        host=host,
        port=port,
        auth_server_provider=oauth_provider,
        auth=auth_settings,
    )

    return auth_server


# Create a default server instance
auth_server = create_auth_server()


def main():
    """Command-line entry point for the Authorization Server."""
    parser = argparse.ArgumentParser(description="MCP OAuth Proxy Authorization Server")
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (overrides AUTH_SERVER_HOST env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (overrides AUTH_SERVER_PORT env var)",
    )
    parser.add_argument(
        "--transport",
        default="streamable-http",
        help="Transport type (streamable-http or websocket)",
    )

    args = parser.parse_args()

    # Use command-line arguments only if provided, otherwise use environment variables
    host = args.host or AUTH_SERVER_HOST
    port = args.port or AUTH_SERVER_PORT

    # Log the configuration being used
    logger.info(f"Starting Authorization Server with host={host}, port={port}")

    # Create a server with the specified configuration
    auth_server = create_auth_server(
        host=host, port=port, auth_settings=auth_settings, oauth_provider=oauth_provider
    )

    logger.info(f"🚀 MCP OAuth Authorization Server running on http://{host}:{port}")
    auth_server.run(transport=args.transport)


if __name__ == "__main__":
    main()
