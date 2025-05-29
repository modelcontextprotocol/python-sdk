"""
Enhanced Tool Definition Interface (ETDI) for Model Context Protocol

ETDI provides OAuth 2.0-based security enhancements to prevent Tool Poisoning
and Rug Pull attacks in MCP implementations.
"""

from .types import (
    ETDIToolDefinition,
    SecurityInfo,
    OAuthInfo,
    Permission,
    ToolApprovalRecord,
    VerificationResult,
    InvocationCheck,
    ChangeDetectionResult,
    SecurityLevel,
    VerificationStatus,
    CallStackConstraints,
)

from .exceptions import (
    ETDIError,
    SignatureError,
    VersionError,
    PermissionError,
    OAuthError,
    ProviderError,
)

# Import core components that don't depend on main MCP
try:
    from .client import (
        ETDIVerifier,
        ApprovalManager,
    )
    _client_available = True
except ImportError:
    _client_available = False

try:
    from .server import (
        OAuthSecurityMiddleware,
        TokenManager,
    )
    _server_available = True
except ImportError:
    _server_available = False

# Import MCP-dependent components only if available
try:
    from .client import (
        ETDIClient,
        ETDISecureClientSession,
    )
    _mcp_client_available = True
except ImportError:
    _mcp_client_available = False

try:
    from .server import (
        ETDISecureServer,
    )
    _mcp_server_available = True
except ImportError:
    _mcp_server_available = False
    ETDISecureServer = None

from .oauth import (
    OAuthProvider,
    Auth0Provider,
    OktaProvider,
    AzureADProvider,
    OAuthManager,
    OAuthConfig,
)

from .inspector import (
    SecurityAnalyzer,
    TokenDebugger,
    OAuthValidator,
    CallStackVerifier,
    CallStackPolicy,
    CallStackViolationType,
)

__version__ = "1.0.0"

# Build __all__ list dynamically based on what's available
__all__ = [
    # Core types (always available)
    "ETDIToolDefinition",
    "SecurityInfo",
    "OAuthInfo",
    "Permission",
    "ToolApprovalRecord",
    "VerificationResult",
    "InvocationCheck",
    "ChangeDetectionResult",
    "SecurityLevel",
    "VerificationStatus",
    "CallStackConstraints",
    
    # Exceptions (always available)
    "ETDIError",
    "SignatureError",
    "VersionError",
    "PermissionError",
    "OAuthError",
    "ProviderError",
    
    # OAuth providers (always available)
    "OAuthProvider",
    "Auth0Provider",
    "OktaProvider",
    "AzureADProvider",
    "OAuthManager",
    "OAuthConfig",
    
    # Inspector tools (always available)
    "SecurityAnalyzer",
    "TokenDebugger",
    "OAuthValidator",
    "CallStackVerifier",
    "CallStackPolicy",
    "CallStackViolationType",
]

# Add client components if available
if _client_available:
    __all__.extend([
        "ETDIVerifier",
        "ApprovalManager",
    ])

if _server_available:
    __all__.extend([
        "OAuthSecurityMiddleware",
        "TokenManager",
    ])

# Add MCP-dependent components if available
if _mcp_client_available:
    __all__.extend([
        "ETDIClient",
        "ETDISecureClientSession",
    ])

# Add ETDISecureServer if it was successfully imported
if _mcp_server_available:
    __all__.extend([
        "ETDISecureServer",
    ])