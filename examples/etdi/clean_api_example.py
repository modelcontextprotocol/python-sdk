#!/usr/bin/env python3
"""
Clean ETDI API Example

Shows how simple it is to add enterprise security to FastMCP tools.
Just add etdi=True and security is automatically enforced!
"""

from mcp.server.fastmcp import FastMCP

# Create server
server = FastMCP("Clean ETDI Example")

# Set user permissions (in real app, this comes from OAuth middleware)
server.set_user_permissions(["data:read", "files:write"])

# 1. Basic tool - no security
@server.tool()
def basic_tool(message: str) -> str:
    """Basic tool with no security"""
    return f"Basic: {message}"

# 2. Simple ETDI security - just add etdi=True!
@server.tool(etdi=True)
def simple_secure_tool(message: str) -> str:
    """Secure tool - automatically protected by ETDI"""
    return f"Secure: {message}"

# 3. ETDI with permissions - specify what permissions are needed
@server.tool(etdi=True, etdi_permissions=["data:read"])
def data_reader(query: str) -> str:
    """Tool that requires data:read permission"""
    return f"Data: {query}"

# 4. ETDI with call restrictions - control what this tool can call
@server.tool(
    etdi=True,
    etdi_permissions=["files:write"],
    etdi_max_call_depth=2,
    etdi_allowed_callees=["data_reader"],
    etdi_blocked_callees=["admin_tool"]
)
def file_processor(filename: str) -> str:
    """Tool with call chain restrictions"""
    return f"Processing file: {filename}"

# 5. Admin tool - requires admin permissions (user doesn't have these)
@server.tool(
    etdi=True,
    etdi_permissions=["admin:dangerous"],
    etdi_max_call_depth=1,
    etdi_allowed_callees=[]
)
def admin_tool(command: str) -> str:
    """Admin tool - will be blocked by ETDI"""
    return f"Admin command: {command}"

def main():
    """Demonstrate the clean API"""
    print("🚀 Clean ETDI API Example")
    print("=" * 40)
    
    print("\n💡 How simple is ETDI security?")
    print("   Just add etdi=True to your @server.tool() decorator!")
    print("   Security is automatically enforced - no extra code needed.")
    
    print("\n📝 Example Tools:")
    print("   • basic_tool() - No security")
    print("   • simple_secure_tool(etdi=True) - Automatic security")
    print("   • data_reader(etdi=True, permissions=['data:read']) - Permission required")
    print("   • file_processor(...) - Full security constraints")
    print("   • admin_tool(...) - Will be blocked (user lacks admin perms)")
    
    print("\n🛡️  Security Features Automatically Enabled:")
    print("   ✅ Permission checking")
    print("   ✅ Call stack verification")
    print("   ✅ Call depth limits")
    print("   ✅ Caller/callee restrictions")
    print("   ✅ Audit logging")
    
    print("\n🎯 Key Benefits:")
    print("   • Zero boilerplate - just etdi=True")
    print("   • Declarative security in decorators")
    print("   • Automatic enforcement")
    print("   • Enterprise-ready out of the box")
    
    print("\n✨ That's it! ETDI makes enterprise security as simple as")
    print("   adding one boolean parameter to your existing decorators.")

if __name__ == "__main__":
    main()