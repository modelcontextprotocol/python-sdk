# Getting Started with ETDI

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

## Verification

Test your setup:

```bash
python examples/etdi/verify_implementation.py
```

This script will verify that ETDI is properly installed and configured.