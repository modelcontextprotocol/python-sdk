"""
Example demonstrating ETDI inspector tools for security analysis and debugging
"""

import asyncio
import logging
from mcp.etdi import ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo
from mcp.etdi.inspector import SecurityAnalyzer, TokenDebugger
from mcp.etdi.oauth import OAuthManager, Auth0Provider
from mcp.etdi.types import OAuthConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demo_security_analyzer():
    """Demonstrate security analysis of ETDI tools"""
    print("\n🔍 Security Analyzer Demo")
    print("=" * 50)
    
    # Create sample tools with different security configurations
    tools = [
        # Well-configured tool
        ETDIToolDefinition(
            id="secure-calculator",
            name="Secure Calculator",
            version="1.2.0",
            description="A secure calculator with proper OAuth protection",
            provider={"id": "trusted-provider", "name": "Trusted Provider Inc."},
            schema={"type": "object", "properties": {"operation": {"type": "string"}}},
            permissions=[
                Permission(
                    name="calculate",
                    description="Perform mathematical calculations",
                    scope="calc:execute",
                    required=True
                ),
                Permission(
                    name="read_history",
                    description="Read calculation history",
                    scope="calc:read",
                    required=False
                )
            ],
            security=SecurityInfo(
                oauth=OAuthInfo(
                    token="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InNlY3VyZS1jYWxjdWxhdG9yIiwiYXVkIjoiaHR0cHM6Ly90ZXN0LWFwaS5leGFtcGxlLmNvbSIsImV4cCI6OTk5OTk5OTk5OSwiaWF0IjoxNjM0NTY3MDAwLCJzY29wZSI6ImNhbGM6ZXhlY3V0ZSBjYWxjOnJlYWQiLCJ0b29sX2lkIjoic2VjdXJlLWNhbGN1bGF0b3IiLCJ0b29sX3ZlcnNpb24iOiIxLjIuMCJ9.signature",
                    provider="auth0"
                )
            )
        ),
        
        # Tool with security issues
        ETDIToolDefinition(
            id="insecure-tool",
            name="Insecure Tool",
            version="0.1",  # Invalid version format
            description="A tool with security issues",
            provider={"id": "", "name": ""},  # Missing provider info
            schema={"type": "object"},
            permissions=[
                Permission(
                    name="admin_access",
                    description="",  # Missing description
                    scope="*",  # Overly broad scope
                    required=True
                )
            ],
            security=SecurityInfo(
                oauth=OAuthInfo(
                    token="invalid.jwt.token",
                    provider="unknown-provider"
                )
            )
        ),
        
        # Tool without security
        ETDIToolDefinition(
            id="legacy-tool",
            name="Legacy Tool",
            version="1.0.0",
            description="A legacy tool without security",
            provider={"id": "legacy-provider", "name": "Legacy Provider"},
            schema={"type": "object"},
            permissions=[],
            security=None
        )
    ]
    
    # Initialize security analyzer
    analyzer = SecurityAnalyzer()
    
    # Analyze each tool
    for tool in tools:
        print(f"\n📊 Analyzing: {tool.name}")
        print("-" * 30)
        
        try:
            result = await analyzer.analyze_tool(tool, detailed_analysis=True)
            
            print(f"Security Score: {result.overall_security_score:.1f}/100")
            print(f"Findings: {len(result.security_findings)} security issues")
            print(f"Permissions: {result.permission_analysis.total_permissions} total")
            
            # Show critical findings
            critical_findings = [f for f in result.security_findings 
                               if f.severity.value == "critical"]
            if critical_findings:
                print("🚨 Critical Issues:")
                for finding in critical_findings:
                    print(f"  - {finding.message}")
            
            # Show recommendations
            if result.recommendations:
                print("💡 Top Recommendations:")
                for rec in result.recommendations[:3]:
                    print(f"  - {rec}")
                    
        except Exception as e:
            print(f"❌ Analysis failed: {e}")
    
    # Analyze multiple tools in parallel
    print(f"\n🔄 Parallel Analysis of {len(tools)} tools...")
    results = await analyzer.analyze_multiple_tools(tools)
    
    # Summary statistics
    avg_score = sum(r.overall_security_score for r in results) / len(results)
    total_findings = sum(len(r.security_findings) for r in results)
    
    print(f"📈 Summary:")
    print(f"  Average Security Score: {avg_score:.1f}/100")
    print(f"  Total Security Findings: {total_findings}")
    print(f"  Tools Analyzed: {len(results)}")


def demo_token_debugger():
    """Demonstrate OAuth token debugging"""
    print("\n🔧 Token Debugger Demo")
    print("=" * 50)
    
    # Sample tokens for debugging
    tokens = {
        "valid_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5In0.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksImlhdCI6MTYzNDU2NzAwMCwic2NvcGUiOiJyZWFkOnRvb2xzIGV4ZWN1dGU6dG9vbHMiLCJ0b29sX2lkIjoidGVzdC10b29sIiwidG9vbF92ZXJzaW9uIjoiMS4wLjAifQ.signature",
        "expired_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJleHAiOjE2MzQ1NjcwMDAsImlhdCI6MTYzNDU2NzAwMCwic2NvcGUiOiJyZWFkOnRvb2xzIn0.signature",
        "invalid_token": "not.a.valid.jwt.token"
    }
    
    debugger = TokenDebugger()
    
    for token_name, token in tokens.items():
        print(f"\n🎫 Debugging: {token_name}")
        print("-" * 30)
        
        try:
            debug_info = debugger.debug_token(token)
            
            print(f"Valid JWT: {'Yes' if debug_info.is_valid_jwt else 'No'}")
            
            if debug_info.is_valid_jwt:
                print(f"ETDI Compliance: {debug_info.etdi_compliance['compliance_score']}/100")
                print(f"Security Issues: {len(debug_info.security_issues)}")
                
                # Show key claims
                etdi_claims = debug_info.etdi_compliance.get('etdi_claims', {})
                if etdi_claims:
                    print("ETDI Claims:")
                    for claim, value in etdi_claims.items():
                        print(f"  {claim}: {value}")
                
                # Show expiration info
                if debug_info.expiration_info.get('has_expiration'):
                    is_expired = debug_info.expiration_info.get('is_expired', False)
                    exp_status = "EXPIRED" if is_expired else "Valid"
                    print(f"Expiration: {exp_status}")
                
                # Show top security issues
                if debug_info.security_issues:
                    print("🚨 Security Issues:")
                    for issue in debug_info.security_issues[:3]:
                        print(f"  - {issue}")
            else:
                print("❌ Invalid JWT format")
                
        except Exception as e:
            print(f"❌ Debug failed: {e}")
    
    # Demonstrate token comparison
    print(f"\n🔄 Token Comparison Demo")
    print("-" * 30)
    
    try:
        comparison = debugger.compare_tokens(
            tokens["valid_token"], 
            tokens["expired_token"]
        )
        
        print(f"Tokens Identical: {'Yes' if comparison['tokens_identical'] else 'No'}")
        print(f"Differences Found: {len(comparison['differences'])}")
        
        if comparison['differences']:
            print("Key Differences:")
            for diff in comparison['differences'][:3]:
                print(f"  {diff['claim']}: {diff['token1_value']} → {diff['token2_value']}")
                
    except Exception as e:
        print(f"❌ Comparison failed: {e}")
    
    # Demonstrate tool info extraction
    print(f"\n🔍 Tool Info Extraction")
    print("-" * 30)
    
    try:
        tool_info = debugger.extract_tool_info(tokens["valid_token"])
        
        if "error" not in tool_info:
            print("Extracted Tool Information:")
            for key, value in tool_info.items():
                if value:
                    print(f"  {key}: {value}")
        else:
            print(f"❌ {tool_info['error']}")
            
    except Exception as e:
        print(f"❌ Extraction failed: {e}")


def demo_detailed_token_report():
    """Demonstrate detailed token debugging report"""
    print("\n📋 Detailed Token Report Demo")
    print("=" * 50)
    
    # Sample token with various claims
    sample_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5LTEyMyJ9.eyJpc3MiOiJodHRwczovL2V0ZGktZGVtby5hdXRoMC5jb20vIiwic3ViIjoiZGVtby1jYWxjdWxhdG9yIiwiYXVkIjoiaHR0cHM6Ly9ldGRpLWFwaS5leGFtcGxlLmNvbSIsImV4cCI6OTk5OTk5OTk5OSwibmJmIjoxNjM0NTY3MDAwLCJpYXQiOjE2MzQ1NjcwMDAsImp0aSI6InVuaXF1ZS10b2tlbi1pZCIsInNjb3BlIjoiY2FsYzpleGVjdXRlIGNhbGM6cmVhZCBjYWxjOndyaXRlIiwidG9vbF9pZCI6ImRlbW8tY2FsY3VsYXRvciIsInRvb2xfdmVyc2lvbiI6IjEuMi4zIiwidG9vbF9wcm92aWRlciI6ImRlbW8tcHJvdmlkZXIiLCJjdXN0b21fY2xhaW0iOiJjdXN0b21fdmFsdWUifQ.signature"
    
    debugger = TokenDebugger()
    
    try:
        debug_info = debugger.debug_token(sample_token)
        report = debugger.format_debug_report(debug_info)
        
        print(report)
        
    except Exception as e:
        print(f"❌ Report generation failed: {e}")


async def demo_oauth_integration():
    """Demonstrate OAuth integration with inspector tools"""
    print("\n🔗 OAuth Integration Demo")
    print("=" * 50)
    
    # This would normally use real OAuth credentials
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="demo-client-id",
        client_secret="demo-client-secret",
        domain="demo.auth0.com"
    )
    
    # Create OAuth manager (would normally initialize with real providers)
    oauth_manager = OAuthManager()
    
    # Create analyzer with OAuth integration
    analyzer = SecurityAnalyzer(oauth_manager)
    
    print("✅ Security analyzer created with OAuth integration")
    print("💡 In a real scenario, this would:")
    print("   - Validate tokens against OAuth providers")
    print("   - Check token signatures using JWKS")
    print("   - Verify issuer and audience claims")
    print("   - Validate scopes against tool permissions")


async def main():
    """Run all inspector demos"""
    print("🔍 ETDI Inspector Tools Demo")
    print("=" * 60)
    
    try:
        # Run security analyzer demo
        await demo_security_analyzer()
        
        # Run token debugger demo
        demo_token_debugger()
        
        # Run detailed report demo
        demo_detailed_token_report()
        
        # Run OAuth integration demo
        await demo_oauth_integration()
        
        print("\n✅ All inspector demos completed successfully!")
        print("\n💡 Inspector Tools Usage:")
        print("   - Use SecurityAnalyzer for comprehensive tool security analysis")
        print("   - Use TokenDebugger for OAuth token inspection and debugging")
        print("   - Integrate with OAuth providers for real-time validation")
        print("   - Generate detailed reports for security auditing")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())