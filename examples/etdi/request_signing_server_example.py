"""
Example demonstrating ETDI request-level signing with FastMCP server
"""

import asyncio
import logging
from mcp.server.fastmcp import FastMCP
from mcp.etdi.types import SecurityLevel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_secure_server_with_request_signing():
    """Create a FastMCP server with request signing enabled"""
    
    # Create FastMCP server with STRICT security level
    server = FastMCP(
        name="Ultra Secure Banking Server",
        version="1.0.0",
        security_level=SecurityLevel.STRICT  # Required for request signing
    )
    
    # Initialize request signing verification
    server.initialize_request_signing()
    
    # Example 1: Regular ETDI tool (no request signing required)
    @server.tool(
        etdi=True,
        etdi_permissions=['banking:read']
    )
    def get_account_balance(account_id: str) -> str:
        """Get account balance - requires OAuth but not request signing"""
        return f"Account {account_id} balance: $1,234.56"
    
    # Example 2: Ultra-secure tool requiring request signing
    @server.tool(
        etdi=True,
        etdi_permissions=['banking:write', 'transactions:execute'],
        etdi_require_request_signing=True  # NEW PARAMETER!
    )
    def transfer_money(from_account: str, to_account: str, amount: float) -> str:
        """Transfer money - requires OAuth AND cryptographic request signing"""
        return f"✅ Transferred ${amount} from {from_account} to {to_account}"
    
    # Example 3: Administrative tool with maximum security
    @server.tool(
        etdi=True,
        etdi_permissions=['admin:full_access'],
        etdi_require_request_signing=True,
        etdi_max_call_depth=1  # No chaining allowed
    )
    def delete_account(account_id: str, confirmation_code: str) -> str:
        """Delete account - maximum security required"""
        if confirmation_code != "DELETE_CONFIRMED":
            raise ValueError("Invalid confirmation code")
        return f"⚠️ Account {account_id} has been deleted"
    
    # Example 4: Tool that works in any security mode (backward compatibility)
    @server.tool(
        etdi=True,
        etdi_permissions=['banking:read'],
        etdi_require_request_signing=True  # Only enforced in STRICT mode
    )
    def get_transaction_history(account_id: str, days: int = 30) -> str:
        """Get transaction history - request signing preferred but not required"""
        return f"Transaction history for {account_id} (last {days} days): [transactions...]"
    
    return server


async def demo_backward_compatibility():
    """Demonstrate backward compatibility with different security levels"""
    print("\n🔄 Backward Compatibility Demo")
    print("=" * 50)
    
    # Test with ENHANCED security level (request signing should warn but not block)
    enhanced_server = FastMCP(
        name="Enhanced Security Server",
        security_level=SecurityLevel.ENHANCED
    )
    
    @enhanced_server.tool(
        etdi=True,
        etdi_permissions=['data:read'],
        etdi_require_request_signing=True  # Will warn but not enforce
    )
    def enhanced_tool(data: str) -> str:
        """Tool with request signing in ENHANCED mode"""
        return f"Processed in ENHANCED mode: {data}"
    
    print("✅ Enhanced server created - request signing will warn but not block")
    
    # Test with BASIC security level
    basic_server = FastMCP(
        name="Basic Security Server",
        security_level=SecurityLevel.BASIC
    )
    
    @basic_server.tool(
        etdi=True,
        etdi_require_request_signing=True  # Will warn but not enforce
    )
    def basic_tool(data: str) -> str:
        """Tool with request signing in BASIC mode"""
        return f"Processed in BASIC mode: {data}"
    
    print("✅ Basic server created - request signing will warn but not block")
    print("🔒 Only STRICT mode enforces request signing for maximum security")


async def demo_key_exchange_integration():
    """Demonstrate integration with key exchange"""
    print("\n🤝 Key Exchange Integration Demo")
    print("=" * 50)
    
    server = create_secure_server_with_request_signing()
    
    # In a real implementation, the server would:
    # 1. Accept key exchange requests from clients
    # 2. Store trusted client public keys
    # 3. Verify request signatures using those keys
    
    print("🔑 Server initialized with request signing")
    print("📋 Available tools:")
    
    # Simulate listing tools with their security requirements
    tools_info = [
        ("get_account_balance", "OAuth only", "✅ Standard security"),
        ("transfer_money", "OAuth + Request Signing", "🔒 Ultra secure"),
        ("delete_account", "OAuth + Request Signing + Call Depth", "🚨 Maximum security"),
        ("get_transaction_history", "OAuth + Request Signing (STRICT only)", "🔄 Backward compatible")
    ]
    
    for tool_name, requirements, security_level in tools_info:
        print(f"  - {tool_name}")
        print(f"    Requirements: {requirements}")
        print(f"    Security: {security_level}")
        print()


def main():
    """Main demonstration"""
    print("🔐 ETDI Request Signing Server Example")
    print("=" * 60)
    
    print("🚀 Creating ultra-secure server with request signing...")
    server = create_secure_server_with_request_signing()
    
    print("✅ Server created with the following security features:")
    print("  - OAuth 2.0 authentication")
    print("  - Permission-based access control")
    print("  - Cryptographic request signing (STRICT mode)")
    print("  - Call stack depth limiting")
    print("  - Full backward compatibility")
    
    # Run compatibility demo
    asyncio.run(demo_backward_compatibility())
    asyncio.run(demo_key_exchange_integration())
    
    print("\n💡 Key Benefits:")
    print("1. ✅ BACKWARD COMPATIBLE - existing tools work unchanged")
    print("2. 🔒 OPTIONAL SECURITY - request signing only when needed")
    print("3. 🎯 STRICT MODE ONLY - enforced only in highest security level")
    print("4. 🔧 SIMPLE API - just add etdi_require_request_signing=True")
    print("5. 🤝 KEY EXCHANGE - automatic public key management")
    
    print("\n🔧 Usage Examples:")
    print("# Standard tool (no changes needed)")
    print("@server.tool()")
    print("def my_tool(): pass")
    print()
    print("# ETDI tool with OAuth")
    print("@server.tool(etdi=True, etdi_permissions=['data:read'])")
    print("def secure_tool(): pass")
    print()
    print("# Ultra-secure tool with request signing")
    print("@server.tool(etdi=True, etdi_require_request_signing=True)")
    print("def ultra_secure_tool(): pass")
    
    print("\n🎉 Request signing successfully integrated!")
    print("   - Zero breaking changes to existing code")
    print("   - Maximum security when needed")
    print("   - Seamless key exchange")


if __name__ == "__main__":
    main()