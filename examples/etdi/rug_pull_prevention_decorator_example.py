#!/usr/bin/env python3
"""
Example demonstrating the rug pull prevention flag in the @tool decorator
"""

import asyncio
from mcp.server.fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Rug Pull Prevention Example")

@app.tool(
    etdi=True,
    etdi_permissions=['data:read'],
    etdi_enable_rug_pull_prevention=True,  # Enable rug pull prevention (default)
    description="A secure tool with rug pull prevention enabled"
)
def secure_tool(data: str) -> str:
    """Process data securely with rug pull protection"""
    return f"Securely processed: {data}"

@app.tool(
    etdi=True,
    etdi_permissions=['legacy:read'],
    etdi_enable_rug_pull_prevention=False,  # Disable rug pull prevention
    description="A legacy tool without rug pull prevention"
)
def legacy_tool(data: str) -> str:
    """Process data without rug pull protection (legacy mode)"""
    return f"Legacy processed: {data}"

@app.tool(
    etdi=True,
    etdi_permissions=['banking:write'],
    # etdi_enable_rug_pull_prevention defaults to True
    description="A banking tool with default rug pull prevention"
)
def banking_tool(amount: float) -> str:
    """Process banking transaction with default rug pull protection"""
    return f"Banking transaction: ${amount}"

def main():
    """Demonstrate the rug pull prevention decorator flags"""
    print("=== Rug Pull Prevention Decorator Example ===\n")
    
    # Check the ETDI metadata on each function
    tools = [
        ("secure_tool", secure_tool),
        ("legacy_tool", legacy_tool),
        ("banking_tool", banking_tool)
    ]
    
    for tool_name, tool_func in tools:
        print(f"Tool: {tool_name}")
        print(f"  ETDI Enabled: {getattr(tool_func, '_etdi_enabled', False)}")
        print(f"  Rug Pull Prevention: {getattr(tool_func, '_etdi_enable_rug_pull_prevention', 'Not set')}")
        
        if hasattr(tool_func, '_etdi_tool_definition'):
            etdi_def = tool_func._etdi_tool_definition
            print(f"  Tool Definition Rug Pull Prevention: {etdi_def.enable_rug_pull_prevention}")
            print(f"  Permissions: {[p.scope for p in etdi_def.permissions]}")
        
        print()
    
    print("=== Summary ===")
    print("✓ secure_tool: Rug pull prevention ENABLED")
    print("✓ legacy_tool: Rug pull prevention DISABLED")
    print("✓ banking_tool: Rug pull prevention ENABLED (default)")
    print("\nThe @tool decorator now supports etdi_enable_rug_pull_prevention flag!")

if __name__ == "__main__":
    main()