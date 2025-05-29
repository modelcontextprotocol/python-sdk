# ETDI Security Features

For a conceptual and architectural overview, see [ETDI Concepts](etdi-concepts.md).

ETDI provides a rich set of security features designed to protect AI tool interactions at multiple levels. These features work together to ensure tool authenticity, enforce access control, monitor behavior, and provide comprehensive auditability.

## 1. Authentication

Ensuring that only legitimate users, services, and tools can interact with the system.

-   **OAuth 2.0 Integration**: ETDI seamlessly integrates with standard OAuth 2.0 providers (e.g., Auth0, Okta, Azure AD) for robust identity verification. This allows leveraging existing enterprise identity systems.
    -   Clients and Servers use OAuth tokens to authenticate.
    -   Support for various flows (Client Credentials, Authorization Code, etc.) depending on the use case.
    -   See `examples/etdi/oauth_providers.py` in the project's example code for configurations.
-   **Single Sign-On (SSO)**: Through OAuth/OIDC providers, ETDI can support enterprise SSO, simplifying user management.
-   **Token Verification**: All API calls requiring authentication are protected. Tokens are cryptographically verified (signatures, expiration, issuer, audience) by both the ETDI client and the secure server middleware.
-   **Mutual TLS (mTLS)**: For service-to-service communication, mTLS can be employed for an additional layer of authentication, ensuring both client and server verify each other's identity using X.509 certificates.

## 2. Authorization

Defining and enforcing what authenticated entities are allowed to do.

-   **Fine-Grained Permissions**: Tools explicitly declare the permissions they require to operate (e.g., `file:read`, `database:user:update`, `api:external_service:call`).
    ```python
    @server.tool("secure_file_read", permissions=["file:read", "audit:log"])
    async def secure_file_read(path: str) -> str:
        # ... implementation
        pass
    ```
-   **Scope-Based Access Control**: OAuth scopes granted to clients are checked against the permissions required by tools. A tool invocation is only allowed if the client possesses all necessary scopes.
-   **Role-Based Access Control (RBAC)**: User roles, often managed by the OAuth provider, can be mapped to sets of permissions or scopes, simplifying authorization management.
-   **Caller/Callee Authorization**: Specific to [Call Stack Security](attack-prevention.md#call-stack-security), this ensures that a tool (caller) is authorized to invoke another tool (callee), and the callee is authorized to be invoked by the caller.

## 3. Tool Integrity & Verification

Ensuring tools are authentic, have not been tampered with, and their versions are managed.

-   **Cryptographic Signatures**: Tool definitions can be cryptographically signed by their providers. ETDI clients verify these signatures to ensure the tool definition hasn't been altered since publication.
-   **Immutable Versioning**: Each version of a tool has a unique identifier, and its definition (including code references or hashes) is immutable. This is key to [Rug Poisoning Protection](attack-prevention/rug-poisoning.md).
-   **Audit Logging for Security Monitoring**: ETDI supports robust audit logging (see section 4). These logs can be fed into external security monitoring systems (like SIEMs) to detect anomalous behavior (e.g., resource access patterns, API call frequency) and trigger alerts or manual intervention. The ETDI framework focuses on providing the necessary data for such external analysis and monitoring systems.
-   **Approval Workflows**: ETDI clients require explicit user approval for new tools or new versions of existing tools, especially if permissions change. This gives users control over which tools can operate on their behalf.

## 3a. Request Signing

ETDI implements cryptographic request signing to ensure the authenticity and integrity of every tool invocation and API request. This feature provides:

- **Supported Algorithms**: RSA (RS256, RS384, RS512) and ECDSA (ES256, ES384, ES512) signatures.
- **Key Management**: Automatic key generation, rotation, and secure persistence using the ETDI key management subsystem.
- **Integration**: Request signing is seamlessly integrated with ETDI tool definitions and is supported by FastMCP servers for both client and server-side verification.
- **Backward Compatibility**: Request signing is non-breaking and existing tools continue to work without modification.

**Implementation:**
- Signing and verification logic is implemented in `src/mcp/etdi/crypto/request_signer.py`.
- Key exchange and management is handled by `src/mcp/etdi/crypto/key_exchange.py`.
- Comprehensive tests are in `tests/etdi/test_request_signing.py`.

**Examples:**
- Client-side signing: `examples/etdi/request_signing_example.py`
- Server-side verification: `examples/etdi/request_signing_server_example.py`
- End-to-end workflow: `examples/etdi/comprehensive_request_signing_example.py`

Request signing provides strong guarantees that requests and tool invocations are authentic and have not been tampered with in transit.

### Best Practices for Request Signing

- Enable request signing for all sensitive or production deployments to ensure authenticity and integrity of requests.
- You can adopt request signing incrementally—existing tools and clients will continue to work without modification.
- Use strong key management practices and rotate keys regularly (handled automatically by ETDI).
- Refer to the provided examples for client-side, server-side, and end-to-end signing workflows.

## 4. Audit Logging

Comprehensive logging of all security-relevant events for monitoring, forensics, and compliance.

-   **Security Events Logged**: 
    -   Tool discovery, verification success/failure.
    -   Tool approval and revocation.
    -   Tool invocation requests (with parameters, if configured).
    -   Authentication success/failure.
    -   Authorization success/failure (permission/scope checks).
    -   Detected security policy violations (e.g., call stack violations).
-   **Standardized Log Format**: Logs can be structured (e.g., JSON) for easy integration with SIEMs and log analysis platforms.
-   **Forensic Analysis**: Detailed logs help in tracing the source and impact of any security incident.

## Configuration Examples

Security features are typically configured when initializing the `SecureServer` or through specific decorators and policies:

```python
from mcp.etdi import SecureServer
from mcp.etdi.types import SecurityPolicy, SecurityLevel # OAuthConfig removed as it might not be directly used here
# from mcp.etdi.auth import OAuthHandler # Assuming this exists for server-side setup

# Example Security Policy
policy = SecurityPolicy(
    security_level=SecurityLevel.HIGH,       # Or STRICT, ENHANCED, BASIC
    require_tool_signatures=True,
    enable_call_chain_validation=True,
    max_call_depth=5,
    audit_all_calls=True,
    # allowed_callers, blocked_callees etc.
)

# Example OAuth Handler Configuration (Conceptual for server-side)
# auth_handler = OAuthHandler(
#     provider="auth0", 
#     domain="your.domain.com", 
#     client_id="clientid", 
#     # ... other params
# )

server = SecureServer(
    name="my-super-secure-server",
    security_policy=policy,
    # oauth_handlers=[auth_handler] # Registering OAuth middleware if applicable
)

@server.tool(
    "my_secure_tool", 
    permissions=["data:read", "user:profile:view"],
    etdi_require_signature=True, # Overrides policy for this tool
    etdi_max_call_depth=3
)
async def my_secure_tool_impl(param: str):
    # Tool logic
    return f"Processed {param} securely"
```

These features provide a robust framework for building secure and trustworthy AI agent and tool ecosystems. Refer to specific examples in the project's `examples/etdi` directory and the API reference for detailed implementation guides.