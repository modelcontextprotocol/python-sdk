# ETDI Security Framework

Enterprise-Grade Security for AI Tool Interactions

Prevent tool poisoning, rug poisoning, and unauthorized access with cryptographic verification, behavioral monitoring, and comprehensive audit trails.

For a deep dive into ETDI concepts and security architecture, see [ETDI Concepts](etdi-concepts.md).

## Key Security Features

- **🛡️ Tool Poisoning Prevention**: Cryptographic signatures and behavioral verification
- **👁️ Rug Poisoning Protection**: Change detection and reapproval workflows  
- **🔐 Call Chain Validation**: Stack constraints and caller/callee authorization
- **🔑 Enterprise Authentication**: OAuth 2.0, SAML, and SSO integration
- **📊 Comprehensive Auditing**: Detailed logs for security events, compliance, and forensics.
- **📈 Data for Monitoring**: Provides rich data to feed into external real-time monitoring and threat detection systems.
- **🔏 Cryptographic Request Signing**: Per-request and per-invocation signatures with RSA/ECDSA, key management, and verification.

## 🔐 Request Signing Implementation

ETDI supports cryptographic request signing for all tool invocations and API requests, using RSA/ECDSA algorithms, automatic key management, and seamless integration with tool definitions and FastMCP servers. For technical details and example usage, see [Security Features](security-features.md#request-signing) and the [Request Signing Examples](examples/index.md).

## 🔐 New Request Signing Implementation

**Cryptographic Request Signing Module:**
- `src/mcp/etdi/crypto/request_signer.py` – RSA/ECDSA request signing and verification
- `src/mcp/etdi/crypto/key_exchange.py` – Secure key exchange and management
- `tests/etdi/test_request_signing.py` – Comprehensive test suite for signing functionality

**Request Signing Features:**
- Multiple Algorithms: Support for RS256, RS384, RS512, ES256, ES384, ES512
- Key Management: Automatic key generation, rotation, and persistence
- Tool Integration: Seamless integration with ETDI tool definitions
- FastMCP Integration: Request signing support for FastMCP servers
- Backward Compatibility: Non-breaking integration with existing tools

**Example Files Added:**
- `examples/etdi/request_signing_example.py` – Client-side request signing
- `examples/etdi/request_signing_server_example.py` – Server-side signature verification
- `examples/etdi/comprehensive_request_signing_example.py` – End-to-end signing workflow

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
