"""OAuth Proxy Server for MCP."""

__version__ = "0.1.0"

# Import key components for easier access
from .auth_server import auth_server as auth_server
from .auth_server import main as auth_server_main
from .combo_server import combo_server as combo_server
from .combo_server import main as combo_server_main
from .resource_server import main as resource_server_main
from .resource_server import resource_server as resource_server
from .token_verifier import IntrospectionTokenVerifier

__all__ = [
    "auth_server",
    "resource_server",
    "combo_server",
    "IntrospectionTokenVerifier",
    "auth_server_main",
    "resource_server_main",
    "combo_server_main",
]

# Aliases for the script entry points
main = combo_server_main
