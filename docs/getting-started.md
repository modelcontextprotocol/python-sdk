# Getting Started with ETDI

For a conceptual overview of ETDI and its security model, see [ETDI Concepts](etdi-concepts.md).

This guide will help you set up the Enhanced Tool Definition Interface (ETDI) security framework and create your first secure AI tool server.

## Prerequisites

- Python 3.11 or higher
- Git
- A text editor or IDE

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/python-sdk-etdi/python-sdk-etdi.git
cd python-sdk-etdi
```

### 2. Set Up Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -e .
```

## Quick Start Example

Create your first secure server:

```python
# secure_server_example.py
import asyncio
from mcp.etdi import SecureServer, ToolProvider
from mcp.etdi.types import SecurityLevel

async def main():
    # Create secure server with high security
    server = SecureServer(
        name="my-secure-server",
        security_level=SecurityLevel.HIGH,
        enable_tool_verification=True
    )
    
    # Register a secure tool
    @server.tool("get_weather")
    async def get_weather(location: str) -> dict:
        """Get weather for a location with security verification."""
        # Tool implementation here
        return {"location": location, "temperature": "72°F"}
    
    # Start the server
    await server.start()

if __name__ == "__main__":
    asyncio.run(main())
```

## Enabling Request Signing

Request signing ensures that every tool invocation and API request is cryptographically signed and verifiable, protecting against tampering and impersonation. ETDI supports RSA and ECDSA algorithms, with automatic key management.

Request signing is non-breaking and can be enabled incrementally—existing tools continue to work without modification.

### Minimal Example

```python
from mcp.etdi import SecureServer

server = SecureServer(
    name="my-secure-server",
    enable_request_signing=True,  # Enable request signing for all tools
)

@server.tool("secure_tool", etdi_require_request_signing=True)
async def secure_tool(data: str) -> str:
    return f"Signed and secure: {data}"
```

For a full end-to-end example, see [Request Signing Example](../examples/etdi/request_signing_example.py).

## Security Configuration

Configure security levels and policies:

```python
from mcp.etdi.types import SecurityPolicy, SecurityLevel

policy = SecurityPolicy(
    security_level=SecurityLevel.HIGH,
    require_tool_signatures=True,
    enable_call_chain_validation=True,
    max_call_depth=10,
    audit_all_calls=True
)

server = SecureServer(security_policy=policy)
```

## Next Steps

- [Authentication Setup](security-features.md): Configure OAuth and enterprise SSO
- [Tool Poisoning Prevention](attack-prevention.md): Protect against malicious tools
- [Examples](examples/index.md): Explore real-world examples and demos
- [Request Signing Example](examples/etdi/request_signing_example.py): See how to implement and use request signing

## Verification

Test your setup:

```bash
python examples/etdi/verify_implementation.py
```

This script will verify that ETDI is properly installed and configured.

## End-to-End ETDI Security Workflow

Follow these steps for a complete, secure ETDI deployment:

1. **Start a Secure Server**
   - Use the Quick Start or Security Configuration examples above to launch a server with ETDI security features enabled.
   - Optionally, enable request signing for all tools (see 'Enabling Request Signing' above).

2. **Run a Secure Client**
   - Use the ETDI client to discover, verify, and approve tools.
   - Example: See `examples/etdi/basic_usage.py` for a minimal client workflow.

3. **Invoke Tools Securely**
   - Invoke tools from the client. If request signing is enabled, all invocations will be cryptographically signed and verified.
   - Example: See `examples/etdi/request_signing_example.py` for client-side signing.

4. **Check Security and Audit Logs**
   - Review server and client output for verification status, approval, and audit logs.
   - Example: See `examples/etdi/verify_implementation.py` to verify your setup.

This workflow ensures that your tools are protected against tampering, impersonation, and unauthorized access, leveraging all core ETDI security features.