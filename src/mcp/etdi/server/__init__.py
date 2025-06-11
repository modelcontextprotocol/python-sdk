"""
ETDI server-side components for OAuth security and tool management
"""

# Import core components that don't depend on main MCP
from .middleware import OAuthSecurityMiddleware
from .token_manager import TokenManager

# Import MCP-dependent components - always try to import
from .secure_server import ETDISecureServer

__all__ = [
    "OAuthSecurityMiddleware",
    "TokenManager",
    "ETDISecureServer",
]