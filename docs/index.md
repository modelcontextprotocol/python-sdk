# ETDI Security Framework

Enterprise-Grade Security for AI Tool Interactions

Prevent tool poisoning, rug poisoning, and unauthorized access with cryptographic verification, behavioral monitoring, and comprehensive audit trails.

## Key Security Features

- **🛡️ Tool Poisoning Prevention**: Cryptographic signatures and behavioral verification
- **👁️ Rug Poisoning Protection**: Change detection and reapproval workflows  
- **🔐 Call Chain Validation**: Stack constraints and caller/callee authorization
- **🔑 Enterprise Authentication**: OAuth 2.0, SAML, and SSO integration
- **📊 Comprehensive Auditing**: Detailed logs for security events, compliance, and forensics.
- **📈 Data for Monitoring**: Provides rich data to feed into external real-time monitoring and threat detection systems.

## Quick Start

```python
from mcp.etdi import SecureServer, ToolProvider
from mcp.etdi.auth import OAuthHandler

# Create secure server with ETDI protection
server = SecureServer(
    security_level="high",
    enable_tool_verification=True
)

# Add OAuth authentication
auth = OAuthHandler(
    provider="auth0",
    domain="your-domain.auth0.com",
    client_id="your-client-id"
)
server.add_auth_handler(auth)

# Register verified tools
@server.tool("secure_file_read")
async def secure_file_read(path: str) -> str:
    # Tool implementation with ETDI security
    return await verified_file_read(path)
```

## Documentation Structure

- [Getting Started](getting-started.md): Installation, setup, and your first secure server.
- [Attack Prevention](attack-prevention.md): Comprehensive protection against AI security threats.
- [Security Features](security-features.md): Authentication, authorization, and behavioral verification.
- [Examples & Demos](examples/index.md): Real-world examples and interactive demonstrations.
