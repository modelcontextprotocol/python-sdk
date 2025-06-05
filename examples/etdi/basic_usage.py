"""
Basic ETDI usage example demonstrating secure tool discovery and invocation
"""

import asyncio
import logging
from mcp.etdi import ETDIClient, OAuthConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Demonstrate basic ETDI functionality"""
    
    # Configure OAuth provider (Auth0 example)
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="your-auth0-client-id",
        client_secret="your-auth0-client-secret",
        domain="your-domain.auth0.com",
        audience="https://your-api.example.com",
        scopes=["read:tools", "execute:tools"]
    )
    
    # Initialize ETDI client
    async with ETDIClient({
        "security_level": "enhanced",
        "oauth_config": oauth_config.to_dict(),
        "allow_non_etdi_tools": True,
        "show_unverified_tools": False
    }) as client:
        
        print("🔐 ETDI Client initialized with enhanced security")
        
        # Get client statistics
        stats = await client.get_stats()
        print(f"📊 Client stats: {stats}")
        
        # Discover available tools
        print("\n🔍 Discovering tools...")
        tools = await client.discover_tools()
        
        if not tools:
            print("❌ No tools discovered")
            return
        
        print(f"✅ Discovered {len(tools)} tools:")
        for tool in tools:
            status_icon = "✅" if tool.verification_status.value == "verified" else "⚠️"
            print(f"  {status_icon} {tool.name} (v{tool.version}) - {tool.verification_status.value}")
            print(f"     Provider: {tool.provider.get('name', 'Unknown')}")
            print(f"     Permissions: {[p.name for p in tool.permissions]}")
        
        # Verify a specific tool
        if tools:
            tool = tools[0]
            print(f"\n🔒 Verifying tool: {tool.name}")
            
            is_verified = await client.verify_tool(tool)
            if is_verified:
                print(f"✅ Tool {tool.name} verification successful")
                
                # Check if tool is already approved
                is_approved = await client.is_tool_approved(tool.id)
                if not is_approved:
                    print(f"📝 Approving tool: {tool.name}")
                    await client.approve_tool(tool)
                    print(f"✅ Tool {tool.name} approved")
                else:
                    print(f"✅ Tool {tool.name} already approved")
                
                # Check for version changes
                version_changed = await client.check_version_change(tool.id)
                if version_changed:
                    print(f"⚠️ Tool {tool.name} version has changed - re-approval may be required")
                
                # Example tool invocation (would fail without actual MCP server)
                try:
                    print(f"\n🚀 Attempting to invoke tool: {tool.name}")
                    result = await client.invoke_tool(tool.id, {"example": "parameter"})
                    print(f"✅ Tool invocation result: {result}")
                except Exception as e:
                    print(f"❌ Tool invocation failed (expected in demo): {e}")
            
            else:
                print(f"❌ Tool {tool.name} verification failed")


if __name__ == "__main__":
    asyncio.run(main())