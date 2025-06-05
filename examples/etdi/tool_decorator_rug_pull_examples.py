#!/usr/bin/env python3
"""
Comprehensive examples of using the rug pull prevention flag in the @tool decorator
"""

from mcp.server.fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Rug Pull Prevention Examples")

# Example 1: Default behavior - rug pull prevention enabled
@app.tool(
    etdi=True,
    etdi_permissions=['data:read'],
    description="A secure tool with default rug pull prevention (enabled)"
)
def secure_data_reader(query: str) -> str:
    """Read data securely with rug pull protection enabled by default"""
    return f"Secure data query result: {query}"

# Example 2: Explicitly enable rug pull prevention
@app.tool(
    etdi=True,
    etdi_permissions=['financial:read', 'financial:write'],
    etdi_enable_rug_pull_prevention=True,  # Explicitly enabled
    description="A financial tool with explicit rug pull prevention"
)
def financial_processor(amount: float, account: str) -> str:
    """Process financial transactions with explicit rug pull protection"""
    return f"Financial transaction: ${amount} for account {account}"

# Example 3: Disable rug pull prevention for legacy tools
@app.tool(
    etdi=True,
    etdi_permissions=['legacy:read'],
    etdi_enable_rug_pull_prevention=False,  # Disabled for legacy compatibility
    description="A legacy tool without rug pull prevention"
)
def legacy_data_processor(data: str) -> str:
    """Process data using legacy methods without rug pull protection"""
    return f"Legacy processing: {data}"

# Example 4: High-security tool with all protections
@app.tool(
    etdi=True,
    etdi_permissions=['banking:write', 'audit:read'],
    etdi_require_request_signing=True,
    etdi_enable_rug_pull_prevention=True,  # Maximum security
    etdi_max_call_depth=3,
    description="Ultra-secure banking tool with all protections"
)
def ultra_secure_banking(transaction_id: str, amount: float) -> str:
    """Ultra-secure banking operations with all security features enabled"""
    return f"Ultra-secure banking transaction {transaction_id}: ${amount}"

# Example 5: Development/testing tool with reduced security
@app.tool(
    etdi=True,
    etdi_permissions=['dev:read', 'dev:write'],
    etdi_enable_rug_pull_prevention=False,  # Disabled for development
    description="Development tool with reduced security for testing"
)
def dev_testing_tool(test_data: str) -> str:
    """Development tool for testing without rug pull protection"""
    return f"Development test result: {test_data}"

# Example 6: Regular MCP tool (no ETDI, no rug pull prevention)
@app.tool(description="Regular MCP tool without ETDI features")
def regular_tool(input_data: str) -> str:
    """Regular MCP tool without any ETDI security features"""
    return f"Regular processing: {input_data}"

def main():
    """Demonstrate the different rug pull prevention configurations"""
    print("=== Tool Decorator Rug Pull Prevention Examples ===\n")
    
    tools = [
        ("secure_data_reader", secure_data_reader, "Default (enabled)"),
        ("financial_processor", financial_processor, "Explicitly enabled"),
        ("legacy_data_processor", legacy_data_processor, "Explicitly disabled"),
        ("ultra_secure_banking", ultra_secure_banking, "Maximum security"),
        ("dev_testing_tool", dev_testing_tool, "Development mode"),
        ("regular_tool", regular_tool, "No ETDI")
    ]
    
    for tool_name, tool_func, description in tools:
        print(f"🔧 {tool_name} ({description})")
        
        if hasattr(tool_func, '_etdi_tool_definition'):
            etdi_def = tool_func._etdi_tool_definition
            print(f"   ✓ ETDI Enabled: True")
            print(f"   🛡️  Rug Pull Prevention: {etdi_def.enable_rug_pull_prevention}")
            print(f"   🔐 Request Signing: {etdi_def.require_request_signing}")
            print(f"   📋 Permissions: {[p.scope for p in etdi_def.permissions]}")
            
            if etdi_def.call_stack_constraints:
                print(f"   📊 Max Call Depth: {etdi_def.call_stack_constraints.max_depth}")
        else:
            print(f"   ✓ ETDI Enabled: False")
            print(f"   🛡️  Rug Pull Prevention: N/A (no ETDI)")
        
        print()
    
    print("=== Usage Guidelines ===")
    print("✅ Enable rug pull prevention (default) for:")
    print("   • Production tools handling sensitive data")
    print("   • Financial and banking operations")
    print("   • User-facing applications")
    print("   • Tools requiring high security")
    print()
    print("⚠️  Consider disabling rug pull prevention for:")
    print("   • Legacy tools requiring backward compatibility")
    print("   • Development and testing environments")
    print("   • Tools with frequent legitimate updates")
    print("   • Performance-critical applications")
    print()
    print("🔒 Always enable for ultra-secure scenarios:")
    print("   • Banking and financial services")
    print("   • Healthcare data processing")
    print("   • Government and compliance tools")
    print("   • Critical infrastructure management")

if __name__ == "__main__":
    main()