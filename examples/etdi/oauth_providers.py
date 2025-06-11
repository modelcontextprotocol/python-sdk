"""
Example demonstrating different OAuth provider configurations for ETDI
"""

import asyncio
import logging
from mcp.etdi import ETDIClient, OAuthConfig
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demo_auth0_provider_with_real_credentials():
    """Demonstrate Auth0 OAuth provider with real credentials"""
    print("\n🔐 Auth0 Provider Demo (Real Credentials)")
    print("=" * 50)
    
    # Use real Auth0 credentials from the MCP tool
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="2XrZkaLO4Tj7xlk4dLysqVVjETg2xNZo",  # ETDI Tool Registry (Test Application)
        client_secret="your-client-secret-here",  # This would need to be retrieved securely
        domain=os.getenv("ETDI_AUTH0_DOMAIN", "your-auth0-domain.auth0.com"),
        audience="https://api.etdi.example.com",  # ETDI Tool Registry API
        scopes=["read", "write", "execute", "admin"]
    )
    
    try:
        async with ETDIClient({
            "security_level": "enhanced",
            "oauth_config": oauth_config.to_dict()
        }) as client:
            stats = await client.get_stats()
            print(f"✅ Auth0 client initialized with real credentials")
            print(f"📊 OAuth providers: {stats.get('oauth_providers', [])}")
            print(f"🔑 Client ID: {oauth_config.client_id}")
            print(f"🌐 Domain: {oauth_config.domain}")
            print(f"🎯 Audience: {oauth_config.audience}")
            print(f"📋 Scopes: {oauth_config.scopes}")
            
            return True
    except Exception as e:
        print(f"❌ Auth0 demo failed: {e}")
        print("Note: This requires a valid client secret from Auth0")
        return False


async def demo_tool_provider_sdk_with_auth0():
    """Demonstrate Tool Provider SDK with Auth0 integration"""
    print("\n🔧 Tool Provider SDK + Auth0 Integration Demo")
    print("=" * 50)
    
    try:
        from mcp.etdi.server.tool_provider import ToolProvider
        from mcp.etdi.types import Permission, OAuthConfig
        from mcp.etdi.oauth import OAuthManager, Auth0Provider
        
        # Create OAuth configuration for Auth0
        oauth_config = OAuthConfig(
            provider="auth0",
            client_id="2XrZkaLO4Tj7xlk4dLysqVVjETg2xNZo",
            client_secret="your-client-secret-here",  # Would be retrieved securely
            domain=os.getenv("ETDI_AUTH0_DOMAIN", "your-auth0-domain.auth0.com"),
            audience="https://api.etdi.example.com",
            scopes=["read", "write", "execute"]
        )
        
        # Create OAuth manager and Auth0 provider
        oauth_manager = OAuthManager()
        auth0_provider = Auth0Provider(oauth_config)
        oauth_manager.register_provider("auth0", auth0_provider)
        
        print(f"✅ OAuth Manager created with Auth0 provider")
        print(f"   Provider: {oauth_config.provider}")
        print(f"   Client ID: {oauth_config.client_id}")
        print(f"   Domain: {oauth_config.domain}")
        print(f"   Audience: {oauth_config.audience}")
        
        # Create a tool provider with OAuth
        provider = ToolProvider(
            provider_id="auth0-demo-provider",
            provider_name="Auth0 Demo Tool Provider",
            private_key=None,  # Using OAuth instead
            oauth_manager=oauth_manager
        )
        
        print(f"✅ Tool Provider created with OAuth integration")
        
        # Register a tool with OAuth authentication
        tool = await provider.register_tool(
            tool_id="auth0-secure-calculator",
            name="Auth0 Secure Calculator",
            version="1.0.0",
            description="A secure calculator tool protected by Auth0 OAuth",
            schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                },
                "required": ["operation", "a", "b"]
            },
            permissions=[
                Permission(
                    name="calculate",
                    description="Perform mathematical calculations",
                    scope="execute",  # Maps to Auth0 scope
                    required=True
                ),
                Permission(
                    name="read_results",
                    description="Read calculation results",
                    scope="read",  # Maps to Auth0 scope
                    required=True
                )
            ],
            use_oauth=True  # Enable OAuth for this tool
        )
        
        print(f"✅ Registered OAuth-protected tool: {tool.name}")
        print(f"   Tool ID: {tool.id}")
        print(f"   Version: {tool.version}")
        print(f"   OAuth Enabled: {tool.security and tool.security.oauth is not None}")
        print(f"   Required Scopes: {[p.scope for p in tool.permissions if p.required]}")
        
        # Update the tool with new permissions
        updated_tool = await provider.update_tool(
            tool_id="auth0-secure-calculator",
            version="1.1.0",
            description="Enhanced secure calculator with Auth0 protection and audit logging",
            permissions=[
                Permission(
                    name="calculate",
                    description="Perform mathematical calculations",
                    scope="execute",
                    required=True
                ),
                Permission(
                    name="read_results",
                    description="Read calculation results",
                    scope="read",
                    required=True
                ),
                Permission(
                    name="audit_access",
                    description="Access audit logs",
                    scope="admin",  # New admin scope
                    required=False
                )
            ]
        )
        
        print(f"✅ Updated tool to version: {updated_tool.version}")
        print(f"   New permissions: {[p.name for p in updated_tool.permissions]}")
        
        # Get provider stats
        stats = provider.get_provider_stats()
        print(f"\n📊 Provider Stats with Auth0 Integration:")
        print(f"   - Total tools: {stats['total_tools']}")
        print(f"   - OAuth enabled tools: {stats['oauth_enabled_tools']}")
        print(f"   - Cryptographically signed tools: {stats['cryptographically_signed_tools']}")
        print(f"   - Auth0 protected tools: {stats['oauth_enabled_tools']}")
        
        # Demonstrate OAuth token validation (simulated)
        print(f"\n🔐 OAuth Token Validation Demo:")
        print(f"   - Token endpoint: {auth0_provider.get_token_endpoint()}")
        print(f"   - JWKS URI: {auth0_provider.get_jwks_uri()}")
        print(f"   - Expected issuer: {auth0_provider._get_expected_issuer()}")
        print(f"   - Required audience: {oauth_config.audience}")
        
        return True
        
    except Exception as e:
        print(f"❌ Tool Provider SDK + Auth0 Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def demo_auth0_provider():
    """Demonstrate Auth0 OAuth provider"""
    print("\n🔐 Auth0 Provider Demo")
    print("=" * 50)
    
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="your-auth0-client-id",
        client_secret="your-auth0-client-secret", 
        domain="your-domain.auth0.com",
        audience="https://your-api.example.com",
        scopes=["read:tools", "execute:tools", "manage:tools"]
    )
    
    async with ETDIClient({
        "security_level": "enhanced",
        "oauth_config": oauth_config.to_dict()
    }) as client:
        stats = await client.get_stats()
        print(f"✅ Auth0 client initialized")
        print(f"📊 OAuth providers: {stats.get('oauth_providers', [])}")


async def demo_okta_provider():
    """Demonstrate Okta OAuth provider"""
    print("\n🔐 Okta Provider Demo")
    print("=" * 50)
    
    oauth_config = OAuthConfig(
        provider="okta",
        client_id="your-okta-client-id",
        client_secret="your-okta-client-secret",
        domain="your-domain.okta.com",
        scopes=["etdi.tools.read", "etdi.tools.execute"]
    )
    
    async with ETDIClient({
        "security_level": "enhanced", 
        "oauth_config": oauth_config.to_dict()
    }) as client:
        stats = await client.get_stats()
        print(f"✅ Okta client initialized")
        print(f"📊 OAuth providers: {stats.get('oauth_providers', [])}")


async def demo_azure_ad_provider():
    """Demonstrate Azure AD OAuth provider"""
    print("\n🔐 Azure AD Provider Demo")
    print("=" * 50)
    
    oauth_config = OAuthConfig(
        provider="azure",
        client_id="your-azure-client-id",
        client_secret="your-azure-client-secret",
        domain="your-tenant-id",  # Can be tenant ID or domain
        scopes=["https://graph.microsoft.com/.default", "api://your-app-id/etdi.tools"]
    )
    
    async with ETDIClient({
        "security_level": "enhanced",
        "oauth_config": oauth_config.to_dict()
    }) as client:
        stats = await client.get_stats()
        print(f"✅ Azure AD client initialized")
        print(f"📊 OAuth providers: {stats.get('oauth_providers', [])}")


async def demo_security_levels():
    """Demonstrate different security levels"""
    print("\n🔒 Security Levels Demo")
    print("=" * 50)
    
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="demo-client-id",
        client_secret="demo-client-secret",
        domain="demo.auth0.com"
    )
    
    # Basic security level
    print("\n📊 Basic Security Level:")
    async with ETDIClient({
        "security_level": "basic",
        "allow_non_etdi_tools": True,
        "show_unverified_tools": True
    }) as client:
        stats = await client.get_stats()
        print(f"  Security level: {stats.get('config', {}).get('security_level')}")
        print(f"  Allow non-ETDI tools: {stats.get('config', {}).get('allow_non_etdi_tools')}")
    
    # Enhanced security level
    print("\n🔒 Enhanced Security Level:")
    async with ETDIClient({
        "security_level": "enhanced",
        "oauth_config": oauth_config.to_dict(),
        "allow_non_etdi_tools": False,
        "show_unverified_tools": False
    }) as client:
        stats = await client.get_stats()
        print(f"  Security level: {stats.get('config', {}).get('security_level')}")
        print(f"  OAuth providers: {stats.get('oauth_providers', [])}")
        print(f"  Allow non-ETDI tools: {stats.get('config', {}).get('allow_non_etdi_tools')}")
    
    # Strict security level
    print("\n🛡️ Strict Security Level:")
    async with ETDIClient({
        "security_level": "strict",
        "oauth_config": oauth_config.to_dict(),
        "allow_non_etdi_tools": False,
        "show_unverified_tools": False,
        "verification_cache_ttl": 60  # Shorter cache for strict mode
    }) as client:
        stats = await client.get_stats()
        print(f"  Security level: {stats.get('config', {}).get('security_level')}")
        print(f"  Cache TTL: {stats.get('config', {}).get('verification_cache_ttl')}s")


async def demo_oauth_token_operations():
    """Demonstrate OAuth token operations"""
    print("\n🎫 OAuth Token Operations Demo")
    print("=" * 50)
    
    from mcp.etdi.oauth import OAuthManager, Auth0Provider
    from mcp.etdi.types import ETDIToolDefinition, Permission
    
    # Create OAuth configuration
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="demo-client-id",
        client_secret="demo-client-secret",
        domain="demo.auth0.com",
        audience="https://demo-api.example.com"
    )
    
    # Create OAuth manager
    oauth_manager = OAuthManager()
    auth0_provider = Auth0Provider(oauth_config)
    oauth_manager.register_provider("auth0", auth0_provider)
    
    print(f"✅ OAuth manager created with providers: {oauth_manager.list_providers()}")
    
    # Create example tool definition
    tool = ETDIToolDefinition(
        id="demo-tool",
        name="Demo Tool",
        version="1.0.0",
        description="A demonstration tool",
        provider={"id": "demo-provider", "name": "Demo Provider"},
        schema={"type": "object"},
        permissions=[
            Permission(
                name="read_data",
                description="Read data from the system",
                scope="read:data",
                required=True
            ),
            Permission(
                name="write_data", 
                description="Write data to the system",
                scope="write:data",
                required=False
            )
        ]
    )
    
    print(f"📋 Created demo tool: {tool.name}")
    print(f"🔑 Tool permissions: {[p.name for p in tool.permissions]}")
    print(f"🎯 Required scopes: {tool.get_permission_scopes()}")
    
    # Note: Actual token operations would require valid OAuth credentials
    print("\n⚠️ Note: Actual token operations require valid OAuth provider credentials")


async def main():
    """Run all OAuth provider demos"""
    print("🚀 ETDI OAuth Providers Demo")
    print("=" * 60)
    
    try:
        # Demo Auth0 with real credentials
        await demo_auth0_provider_with_real_credentials()
        
        # Demo Tool Provider SDK with Auth0 integration
        await demo_tool_provider_sdk_with_auth0()
        
        # Demo different providers (will fail without real credentials)
        await demo_auth0_provider()
        await demo_okta_provider() 
        await demo_azure_ad_provider()
        
        # Demo security levels
        await demo_security_levels()
        
        # Demo token operations
        await demo_oauth_token_operations()
        
        print("\n✅ All demos completed successfully!")
        print("\n💡 To use with real OAuth providers:")
        print("   1. Replace demo credentials with real ones")
        print("   2. Configure OAuth provider applications")
        print("   3. Set appropriate scopes and audiences")
        print("   4. Test with actual MCP servers")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        print("This is expected when running without real OAuth credentials")


if __name__ == "__main__":
    asyncio.run(main())