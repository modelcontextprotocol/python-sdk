# ETDI Examples - Enhanced Tool Definition Interface

This directory contains comprehensive examples demonstrating how ETDI (Enhanced Tool Definition Interface) transforms MCP from a development protocol into an enterprise-ready security platform.

## 🚀 Quick Start

Run the complete end-to-end security demonstration:

```bash
# Ensure you are in the project root directory
python examples/etdi/run_e2e_demo.py
```

This will show ETDI blocking real security attacks including:
- ✅ Call chain restriction enforcement
- ✅ Call depth limit validation  
- ✅ Permission scope verification

## 📁 Example Files

This section provides an overview of the ETDI examples. Each example has its own detailed documentation page.

### Core Security Demonstrations

-   **[`run_e2e_demo.py`](run_e2e_demo.md)** - **START HERE**: Complete end-to-end demonstration showing ETDI blocking real attacks.
-   **[`e2e_secure_server.py`](e2e_secure_server.md)** - Secure Banking Server: FastMCP server with ETDI security demonstrating enterprise-grade protection.
-   **[`e2e_secure_client.py`](e2e_secure_client.md)** - Secure Banking Client: Client that safely interacts with ETDI-secured servers.
-   **[`legitimate_etdi_server.py`](legitimate_etdi_server.md)**: Example of a legitimate, fully secured ETDI server used in demos.

### FastMCP Integration

-   **[`etdi_fastmcp_example.py`](../../fastmcp/index.md)**: Shows how to enable ETDI security with simple boolean flags in FastMCP decorators. (Located in `examples/fastmcp/`)

### Security Components & Features

-   **[`basic_usage.py`](basic_usage.md)** - ETDI Fundamentals: Basic ETDI tool creation and security analysis.
-   **[`oauth_providers.py`](oauth_providers.md)** - Enterprise Authentication: OAuth 2.0 integration with enterprise identity providers.
-   **[`secure_server_example.py`](secure_server_example.md)** - Advanced Server Security: Comprehensive server security with middleware and token management.
-   **[`inspector_example.py`](inspector_example.md)** - Security Analysis Tools: Demonstrates `SecurityAnalyzer` and `TokenDebugger`.
-   **[`demo_etdi.py`](demo_etdi.md)**: Comprehensive demo of various ETDI features.

### Call Stack Security

-   **[`call_stack_example.py`](call_stack_example.md)** - Call Stack Verification: Demonstrates protocol-level call stack security.
-   **[`protocol_call_stack_example.py`](protocol_call_stack_example.md)** - Protocol Integration: Shows how call stack constraints are embedded in tool definitions.
-   **[`caller_callee_authorization_example.py`](caller_callee_authorization_example.md)** - Authorization Matrix: Detailed caller/callee authorization demonstration.

### Utility & Setup Examples

-   **[`clean_api_example.py`](clean_api_example.md)**: Clean API usage for ETDI tool registration and invocation.
-   **[`setup_etdi.py`](setup_etdi.md)**: Script to assist in setting up the ETDI environment or initial configurations.
-   **[`test_complete_security.py`](test_complete_security.md)**: Test suite for complete security validation.
-   **[`verify_implementation.py`](verify_implementation.md)**: Verifies ETDI installation and configuration.

### Request Signing Examples

- **`request_signing_example.py`**: Demonstrates client-side request signing using RSA/ECDSA algorithms.
- **`request_signing_server_example.py`**: Shows server-side signature verification for incoming requests.
- **`comprehensive_request_signing_example.py`**: Provides an end-to-end workflow for request signing and verification between client and server.

### Specific Attack Demonstrations

-   **[Tool Poisoning Demo](./tool_poisoning_demo.md)**: Contains a live demonstration of tool poisoning attacks and ETDI's prevention mechanisms. (Corresponds to `examples/etdi/tool_poisoning_demo/`)

## 🛡️ Security Features Demonstrated Across Examples

Many examples showcase these core ETDI capabilities:

1.  **Tool Poisoning Prevention**: Cryptographic signature verification, provider authentication, tool integrity validation.
2.  **Rug Pull Attack Protection**: Version locking, change detection, behavior verification, reapproval workflows. (See [Rug Poisoning Documentation](../../attack-prevention/rug-poisoning.md))
3.  **Privilege Escalation Blocking**: Permission scope enforcement, call chain restrictions, OAuth integration.
4.  **Call Stack Security**: Maximum depth limits, allowed/blocked callee lists, real-time verification.
5.  **Enterprise Compliance**: Comprehensive audit trails, automated compliance checking, security scoring and reporting.

## 🏢 Illustrative Enterprise Use Cases

These snippets illustrate how ETDI features might be applied in various sensitive contexts.

### Financial Services
```python
@server.tool(etdi=True, etdi_permissions=["trading:read"])
def get_portfolio():  # Can only read, never trade
    pass

@server.tool(etdi=True, etdi_permissions=["trading:execute"], 
             etdi_max_call_depth=1)  # Cannot chain to other tools
def execute_trade():  # Isolated, audited, verified
    pass
```

### Healthcare
```python
@server.tool(etdi=True, etdi_permissions=["patient:read:anonymized"])
def research_query():  # Only anonymized data
    pass

@server.tool(etdi=True, etdi_permissions=["patient:read:identified"],
             etdi_allowed_callees=[])  # Cannot call other tools
def doctor_lookup():  # Isolated access to identified data
    pass
```

### Government/Defense
```python
@server.tool(etdi=True, etdi_permissions=["classified:secret"],
             etdi_blocked_callees=["network", "external"])
def process_classified():  # Cannot leak data externally
    pass
```

## 🚀 Getting Started with Examples

1.  **Run a demo**: Navigate to the project root and execute an example script, e.g., `python examples/etdi/run_e2e_demo.py`.
2.  **Explore FastMCP integration**: See the [FastMCP ETDI Integration page](../../fastmcp/index.md).
3.  **Read detailed pages**: Browse the specific documentation pages for each example linked above.
4.  **Build secure tools**: Use ETDI decorators and principles in your own servers, referring to these examples.

## 💡 Key Benefits

**For Developers**: Security becomes as easy as adding `etdi=True` (with FastMCP) or using ETDI-aware server/client classes.
**For Enterprises**: Meet compliance requirements out of the box with robust security controls.
**For Users**: Trust that tools are verified and operate within constrained boundaries.
**For the Industry**: Raise the security bar for all MCP implementations.

ETDI transforms MCP from a development protocol into an enterprise-ready platform that can handle the most sensitive data and critical operations with confidence. 