"""
ETDI client-side components for tool verification and approval management
"""

# Import core components that don't depend on main MCP
from .verifier import ETDIVerifier
from .approval_manager import ApprovalManager

# Import MCP-dependent components only if available
try:
    from .secure_session import ETDISecureClientSession
    from .etdi_client import ETDIClient
    _mcp_available = True
except ImportError:
    _mcp_available = False

__all__ = [
    "ETDIVerifier",
    "ApprovalManager",
]

if _mcp_available:
    __all__.extend([
        "ETDISecureClientSession",
        "ETDIClient",
    ])