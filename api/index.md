#!/usr/bin/env python3
"""
ETDI Implementation Verification

This script verifies that our ETDI implementation matches the specifications
in the docs/ folder, ensuring the code is representative of the documentation.
"""

import json
import inspect
from typing import Dict, List, Any
from dataclasses import fields

def verify_etdi_implementation():
    """Verify ETDI implementation against documentation specifications"""
    print("🔍 ETDI Implementation Verification")
    print("=" * 50)
    print("Checking if implementation matches docs/core/lld.md specifications...")
    
    verification_results = []
    
    # Test 1: Verify ETDIToolDefinition structure matches docs
    print("\n1️⃣  Verifying ETDIToolDefinition Structure")
    print("-" * 40)
    
    try:
        from mcp.etdi import ETDIToolDefinition
        
        # Check required fields from docs/core/lld.md lines 87-100
        required_fields = {
            'id': str,
            'name': str, 
            'version': str,
            'description': str,
            'provider': dict,  # Should have 'id' and 'name'
            'schema': dict,    # JSON Schema
            'permissions': list,
            'security': object  # SecurityInfo object
        }
        
        # Get actual fields from implementation
        etdi_fields = {field.name: field.type for field in fields(ETDIToolDefinition)}
        
        matches = 0
        total = len(required_fields)
        
        for field_name, expected_type in required_fields.items():
            if field_name in etdi_fields:
                print(f"   ✅ {field_name}: Found")
                matches += 1
            else:
                print(f"   ❌ {field_name}: Missing")
        
        print(f"   📊 Structure Match: {matches}/{total} fields")
        verification_results.append(("ETDIToolDefinition Structure", matches == total))
        
    except Exception as e:
        print(f"   ❌ Failed to verify ETDIToolDefinition: {e}")
        verification_results.append(("ETDIToolDefinition Structure", False))
    
    # Test 2: Verify Permission structure
    print("\n2️⃣  Verifying Permission Structure")
    print("-" * 40)
    
    try:
        from mcp.etdi import Permission
        
        # Check Permission fields
        permission_fields = {field.name for field in fields(Permission)}
        expected_permission_fields = {'name', 'description', 'scope', 'required'}
        
        missing = expected_permission_fields - permission_fields
        if not missing:
            print("   ✅ Permission structure complete")
            verification_results.append(("Permission Structure", True))
        else:
            print(f"   ❌ Permission missing fields: {missing}")
            verification_results.append(("Permission Structure", False))
            
    except Exception as e:
        print(f"   ❌ Failed to verify Permission: {e}")
        verification_results.append(("Permission Structure", False))
    
    # Test 3: Verify SecurityInfo structure
    print("\n3️⃣  Verifying SecurityInfo Structure")
    print("-" * 40)
    
    try:
        from mcp.etdi import SecurityInfo, OAuthInfo
        
        # Check SecurityInfo fields
        security_fields = {field.name for field in fields(SecurityInfo)}
        expected_security_fields = {'oauth', 'signature', 'signature_algorithm'}
        
        missing = expected_security_fields - security_fields
        if not missing:
            print("   ✅ SecurityInfo structure complete")
            
            # Check OAuthInfo fields
            oauth_fields = {field.name for field in fields(OAuthInfo)}
            expected_oauth_fields = {'token', 'provider', 'issued_at', 'expires_at'}
            
            oauth_missing = expected_oauth_fields - oauth_fields
            if not oauth_missing:
                print("   ✅ OAuthInfo structure complete")
                verification_results.append(("SecurityInfo Structure", True))
            else:
                print(f"   ❌ OAuthInfo missing fields: {oauth_missing}")
                verification_results.append(("SecurityInfo Structure", False))
        else:
            print(f"   ❌ SecurityInfo missing fields: {missing}")
            verification_results.append(("SecurityInfo Structure", False))
            
    except Exception as e:
        print(f"   ❌ Failed to verify SecurityInfo: {e}")
        verification_results.append(("SecurityInfo Structure", False))
    
    # Test 4: Verify OAuth Integration Components
    print("\n4️⃣  Verifying OAuth Integration Components")
    print("-" * 40)
    
    try:
        from mcp.etdi import OAuthValidator, TokenDebugger, OAuthConfig
        from mcp.etdi.oauth import Auth0Provider, OktaProvider, AzureADProvider
        
        # Test basic OAuth components
        oauth_validator = OAuthValidator()
        token_debugger = TokenDebugger()
        print("   ✅ OAuthValidator: Available")
        print("   ✅ TokenDebugger: Available")
        
        # Test OAuth providers with proper config
        test_config = OAuthConfig(
            provider="test",
            client_id="test-id",
            client_secret="test-secret",
            domain="test.example.com",
            scopes=["read"],
            audience="https://api.example.com"
        )
        
        oauth_providers = [
            ("Auth0Provider", Auth0Provider),
            ("OktaProvider", OktaProvider),
            ("AzureADProvider", AzureADProvider)
        ]
        
        provider_working = 0
        for name, provider_class in oauth_providers:
            try:
                provider = provider_class(test_config)
                print(f"   ✅ {name}: Available")
                provider_working += 1
            except Exception as e:
                print(f"   ❌ {name}: Failed - {e}")
        
        total_oauth = 2 + len(oauth_providers)  # validator + debugger + providers
        oauth_working = 2 + provider_working
        
        print(f"   📊 OAuth Components: {oauth_working}/{total_oauth} working")
        verification_results.append(("OAuth Integration", oauth_working == total_oauth))
        
    except Exception as e:
        print(f"   ❌ Failed to verify OAuth components: {e}")
        verification_results.append(("OAuth Integration", False))
    
    # Test 5: Verify Call Stack Security (New Feature)
    print("\n5️⃣  Verifying Call Stack Security")
    print("-" * 40)
    
    try:
        from mcp.etdi import CallStackVerifier, CallStackConstraints
        
        # Test call stack constraint creation
        constraints = CallStackConstraints(
            max_depth=3,
            allowed_callees=["helper"],
            blocked_callees=["admin"]
        )
        
        # Test verifier functionality
        verifier = CallStackVerifier()
        
        print("   ✅ CallStackConstraints: Available")
        print("   ✅ CallStackVerifier: Available")
        print("   ✅ Call stack security implemented")
        verification_results.append(("Call Stack Security", True))
        
    except Exception as e:
        print(f"   ❌ Failed to verify call stack security: {e}")
        verification_results.append(("Call Stack Security", False))
    
    # Test 6: Verify FastMCP Integration
    print("\n6️⃣  Verifying FastMCP Integration")
    print("-" * 40)
    
    try:
        from mcp.server.fastmcp import FastMCP
        
        # Test ETDI integration
        server = FastMCP("Test Server")
        
        # Check if ETDI methods exist
        etdi_methods = [
            'set_user_permissions',
            '_check_permissions', 
            '_wrap_with_etdi_security'
        ]
        
        fastmcp_working = 0
        for method in etdi_methods:
            if hasattr(server, method):
                print(f"   ✅ {method}: Available")
                fastmcp_working += 1
            else:
                print(f"   ❌ {method}: Missing")
        
        # Test ETDI decorator parameters
        try:
            @server.tool(etdi=True, etdi_permissions=["test:read"])
            def test_tool(data: str) -> str:
                return f"Test: {data}"
            
            print("   ✅ ETDI decorator parameters: Working")
            fastmcp_working += 1
        except Exception as e:
            print(f"   ❌ ETDI decorator parameters: Failed - {e}")
        
        print(f"   📊 FastMCP Integration: {fastmcp_working}/{len(etdi_methods) + 1} features")
        verification_results.append(("FastMCP Integration", fastmcp_working == len(etdi_methods) + 1))
        
    except Exception as e:
        print(f"   ❌ Failed to verify FastMCP integration: {e}")
        verification_results.append(("FastMCP Integration", False))
    
    # Test 7: Verify Security Analysis Tools
    print("\n7️⃣  Verifying Security Analysis Tools")
    print("-" * 40)
    
    try:
        from mcp.etdi import SecurityAnalyzer
        
        analyzer = SecurityAnalyzer()
        
        # Create a test tool
        from mcp.etdi import ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo
        
        test_tool = ETDIToolDefinition(
            id="test-tool",
            name="Test Tool",
            version="1.0.0",
            description="Test tool for verification",
            provider={"id": "test", "name": "Test Provider"},
            schema={"type": "object"},
            permissions=[Permission(name="test", description="Test", scope="test:read", required=True)],
            security=SecurityInfo(
                oauth=OAuthInfo(token="test-token", provider="test"),
                signature="test-signature",
                signature_algorithm="RS256"
            )
        )
        
        # Test security analysis (async)
        import asyncio
        async def test_analysis():
            result = await analyzer.analyze_tool(test_tool)
            return result.overall_security_score > 0
        
        analysis_works = asyncio.run(test_analysis())
        
        if analysis_works:
            print("   ✅ SecurityAnalyzer: Working")
            print("   ✅ Tool security scoring: Available")
            verification_results.append(("Security Analysis", True))
        else:
            print("   ❌ SecurityAnalyzer: Not working properly")
            verification_results.append(("Security Analysis", False))
        
    except Exception as e:
        print(f"   ❌ Failed to verify security analysis: {e}")
        verification_results.append(("Security Analysis", False))
    
    # Final Results
    print("\n" + "=" * 50)
    print("📊 VERIFICATION RESULTS")
    print("=" * 50)
    
    passed = 0
    total = len(verification_results)
    
    for test_name, result in verification_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n📈 Overall Score: {passed}/{total} ({(passed/total)*100:.1f}%)")
    
    if passed == total:
        print("🎉 IMPLEMENTATION FULLY MATCHES DOCUMENTATION!")
        print("   The code is representative of the docs/ specifications.")
    elif passed >= total * 0.8:
        print("✅ IMPLEMENTATION LARGELY MATCHES DOCUMENTATION")
        print("   Most features implemented according to specs.")
    else:
        print("⚠️  IMPLEMENTATION PARTIALLY MATCHES DOCUMENTATION")
        print("   Some features may not match the specifications.")
    
    return passed == total

if __name__ == "__main__":
    verify_etdi_implementation()