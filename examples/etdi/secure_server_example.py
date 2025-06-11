"""
Example of creating a secure MCP server with ETDI OAuth protection
"""

import asyncio
import logging
from mcp.etdi import ETDISecureServer, OAuthConfig, Permission, ETDIToolDefinition

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Demonstrate ETDI secure server functionality"""
    
    # Configure OAuth providers
    oauth_configs = [
        OAuthConfig(
            provider="auth0",
            client_id="your-auth0-client-id",
            client_secret="your-auth0-client-secret",
            domain="your-domain.auth0.com",
            audience="https://your-api.example.com",
            scopes=["read:tools", "execute:tools"]
        )
    ]
    
    # Create secure server
    server = ETDISecureServer(
        oauth_configs=oauth_configs,
        name="Demo ETDI Server",
        version="1.0.0"
    )
    
    # Initialize server
    await server.initialize()
    print("🔐 ETDI Secure Server initialized")
    
    # Example 1: Using the @secure_tool decorator
    @server.secure_tool(permissions=["read:data", "write:data"])
    async def secure_calculator(operation: str, a: float, b: float) -> float:
        """A secure calculator tool that requires OAuth authentication"""
        if operation == "add":
            return a + b
        elif operation == "subtract":
            return a - b
        elif operation == "multiply":
            return a * b
        elif operation == "divide":
            if b == 0:
                raise ValueError("Cannot divide by zero")
            return a / b
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    print("✅ Registered secure calculator tool")
    
    # Example 2: Manually registering a tool with ETDI
    async def secure_file_reader(filename: str) -> str:
        """Read a file securely with OAuth protection"""
        # In a real implementation, this would read the file
        return f"Contents of {filename}: [SECURE DATA]"
    
    file_reader_tool = ETDIToolDefinition(
        id="secure_file_reader",
        name="Secure File Reader",
        version="1.0.0",
        description="Read files with OAuth protection",
        provider={"id": "demo-provider", "name": "Demo Provider"},
        schema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "File to read"}
            },
            "required": ["filename"]
        },
        permissions=[
            Permission(
                name="read:files",
                description="Read files from the system",
                scope="read:files",
                required=True
            )
        ]
    )
    
    enhanced_tool = await server.register_etdi_tool(
        file_reader_tool,
        secure_file_reader
    )
    print(f"✅ Registered {enhanced_tool.name} with OAuth token")
    
    # Example 3: Adding security hooks
    async def security_audit_hook(data):
        """Log security events for auditing"""
        print(f"🔍 Security Event: {data}")
    
    server.add_security_hook("tool_enhanced", security_audit_hook)
    server.add_security_hook("tool_invocation_validated", security_audit_hook)
    
    # Example 4: Adding tool enhancers
    def add_metadata_enhancer(tool: ETDIToolDefinition) -> ETDIToolDefinition:
        """Add custom metadata to tools"""
        if not hasattr(tool, 'metadata'):
            tool.metadata = {}
        tool.metadata['enhanced_at'] = "2024-01-01T00:00:00Z"
        tool.metadata['security_level'] = "high"
        return tool
    
    server.add_tool_enhancer(add_metadata_enhancer)
    
    # Get server status
    status = await server.get_security_status()
    print(f"\n📊 Server Security Status:")
    print(f"  Total tools: {status['total_tools']}")
    print(f"  Secured tools: {status['secured_tools']}")
    print(f"  OAuth providers: {status['oauth_providers']}")
    
    # List all ETDI tools
    tools = await server.list_etdi_tools()
    print(f"\n🔧 Registered ETDI Tools:")
    for tool in tools:
        oauth_status = "✅ OAuth" if tool.security and tool.security.oauth else "❌ No OAuth"
        print(f"  - {tool.name} (v{tool.version}) - {oauth_status}")
        print(f"    Permissions: {[p.name for p in tool.permissions]}")
        if tool.security and tool.security.oauth:
            print(f"    Provider: {tool.security.oauth.provider}")
    
    # Example 5: Token refresh
    print(f"\n🔄 Refreshing tokens...")
    refresh_results = await server.refresh_tool_tokens()
    for tool_id, success in refresh_results.items():
        status_icon = "✅" if success else "❌"
        print(f"  {status_icon} {tool_id}")
    
    # Cleanup
    await server.cleanup()
    print("\n🧹 Server cleaned up")


async def demo_tool_invocation():
    """Demonstrate tool invocation with security validation"""
    print("\n🚀 Tool Invocation Demo")
    print("=" * 50)
    
    # This would normally be done by an MCP client
    # Here we simulate the process
    
    oauth_configs = [
        OAuthConfig(
            provider="auth0",
            client_id="demo-client-id",
            client_secret="demo-client-secret",
            domain="demo.auth0.com"
        )
    ]
    
    server = ETDISecureServer(oauth_configs)
    await server.initialize()
    
    @server.secure_tool(permissions=["demo:execute"])
    async def demo_tool(message: str) -> str:
        """A demo tool for testing invocation"""
        return f"Demo response: {message}"
    
    # Simulate tool invocation (would normally come from MCP client)
    try:
        # This would fail because we don't have proper OAuth context
        result = await demo_tool("Hello, ETDI!")
        print(f"✅ Tool result: {result}")
    except Exception as e:
        print(f"❌ Tool invocation failed (expected): {e}")
        print("   In a real scenario, this would work with proper OAuth tokens")
    
    await server.cleanup()


if __name__ == "__main__":
    print("🔐 ETDI Secure Server Examples")
    print("=" * 60)
    
    asyncio.run(main())
    asyncio.run(demo_tool_invocation())
    
    print("\n💡 Next Steps:")
    print("1. Configure real OAuth provider credentials")
    print("2. Set up MCP client with ETDI support")
    print("3. Test end-to-end secure tool invocation")
    print("4. Monitor security events and audit logs")