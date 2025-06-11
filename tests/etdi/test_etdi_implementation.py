#!/usr/bin/env python3
"""
ETDI Implementation Validation Script

This script runs comprehensive tests to validate that ETDI works correctly,
including both positive and negative test scenarios.
"""

import sys
import asyncio
import tempfile
import json
from pathlib import Path
from typing import List, Dict, Any

# Add src to path for testing
sys.path.insert(0, str(Path(__file__).parent / "src"))

def print_section(title: str):
    """Print a test section header"""
    print(f"\n{'='*60}")
    print(f"🧪 {title}")
    print('='*60)

def print_test(test_name: str, passed: bool, details: str = ""):
    """Print test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} {test_name}")
    if details:
        print(f"    {details}")

async def test_basic_imports():
    """Test that all ETDI components can be imported"""
    print_section("Basic Import Tests")
    
    tests = []
    
    try:
        from mcp.etdi import ETDIClient
        tests.append(("ETDIClient import", True))
    except Exception as e:
        tests.append(("ETDIClient import", False, str(e)))
    
    try:
        from mcp.etdi import SecurityAnalyzer, TokenDebugger, OAuthValidator
        tests.append(("Inspector tools import", True))
    except Exception as e:
        tests.append(("Inspector tools import", False, str(e)))
    
    try:
        from mcp.etdi import ETDISecureServer
        tests.append(("ETDISecureServer import", True))
    except Exception as e:
        tests.append(("ETDISecureServer import", False, str(e)))
    
    try:
        from mcp.etdi.oauth import OAuthManager, Auth0Provider, OktaProvider, AzureADProvider
        tests.append(("OAuth providers import", True))
    except Exception as e:
        tests.append(("OAuth providers import", False, str(e)))
    
    try:
        from mcp.etdi import ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo
        tests.append(("Core types import", True))
    except Exception as e:
        tests.append(("Core types import", False, str(e)))
    
    for test in tests:
        print_test(*test)
    
    return all(test[1] for test in tests)

async def test_positive_scenarios():
    """Test positive scenarios - things that should work"""
    print_section("Positive Scenario Tests")
    
    from mcp.etdi import (
        SecurityAnalyzer, TokenDebugger, OAuthValidator,
        ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo, OAuthConfig
    )
    
    tests = []
    
    # Test 1: Valid OAuth configuration
    try:
        oauth_config = OAuthConfig(
            provider="auth0",
            client_id="test-client-id",
            client_secret="test-client-secret",
            domain="test.auth0.com",
            audience="https://test-api.example.com"
        )
        
        validator = OAuthValidator()
        result = await validator.validate_provider("auth0", oauth_config)
        
        # Should pass configuration validation
        passed = result.configuration_valid
        details = f"Config valid: {passed}, Provider: {result.provider_name}"
        tests.append(("Valid OAuth configuration", passed, details))
        
    except Exception as e:
        tests.append(("Valid OAuth configuration", False, str(e)))
    
    # Test 2: Valid tool security analysis
    try:
        valid_tool = ETDIToolDefinition(
            id="test-tool",
            name="Test Tool",
            version="1.0.0",
            description="A valid test tool",
            provider={"id": "test-provider", "name": "Test Provider"},
            schema={"type": "object"},
            permissions=[
                Permission(
                    name="read_data",
                    description="Read data from the system",
                    scope="read:data",
                    required=True
                )
            ],
            security=SecurityInfo(
                oauth=OAuthInfo(
                    token="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksImlhdCI6MTYzNDU2NzAwMCwic2NvcGUiOiJyZWFkOmRhdGEiLCJ0b29sX2lkIjoidGVzdC10b29sIiwidG9vbF92ZXJzaW9uIjoiMS4wLjAifQ.signature",
                    provider="auth0"
                )
            )
        )
        
        analyzer = SecurityAnalyzer()
        result = await analyzer.analyze_tool(valid_tool)
        
        # Valid tool should have decent security score
        passed = result.overall_security_score > 50
        details = f"Security score: {result.overall_security_score:.1f}/100"
        tests.append(("Valid tool security analysis", passed, details))
        
    except Exception as e:
        tests.append(("Valid tool security analysis", False, str(e)))
    
    # Test 3: Valid JWT token debugging
    try:
        debugger = TokenDebugger()
        valid_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksImlhdCI6MTYzNDU2NzAwMCwic2NvcGUiOiJyZWFkOnRvb2xzIGV4ZWN1dGU6dG9vbHMiLCJ0b29sX2lkIjoidGVzdC10b29sIiwidG9vbF92ZXJzaW9uIjoiMS4wLjAifQ.signature"
        
        debug_info = debugger.debug_token(valid_token)
        
        passed = debug_info.is_valid_jwt and debug_info.etdi_compliance["compliance_score"] > 60
        details = f"JWT valid: {debug_info.is_valid_jwt}, ETDI compliance: {debug_info.etdi_compliance['compliance_score']}/100"
        tests.append(("Valid JWT token debugging", passed, details))
        
    except Exception as e:
        tests.append(("Valid JWT token debugging", False, str(e)))
    
    # Test 4: Tool approval workflow
    try:
        from mcp.etdi.client import ApprovalManager
        
        with tempfile.TemporaryDirectory() as temp_dir:
            approval_manager = ApprovalManager(storage_path=temp_dir)
            
            # Should not be approved initially
            is_approved_before = await approval_manager.is_tool_approved("test-tool")
            
            # Approve the tool
            record = await approval_manager.approve_tool_with_etdi(valid_tool)
            
            # Should be approved now
            is_approved_after = await approval_manager.is_tool_approved("test-tool")
            
            passed = not is_approved_before and is_approved_after
            details = f"Before: {is_approved_before}, After: {is_approved_after}"
            tests.append(("Tool approval workflow", passed, details))
            
    except Exception as e:
        tests.append(("Tool approval workflow", False, str(e)))
    
    for test in tests:
        print_test(*test)
    
    return all(test[1] for test in tests)

async def test_negative_scenarios():
    """Test negative scenarios - things that should fail safely"""
    print_section("Negative Scenario Tests")
    
    from mcp.etdi import (
        SecurityAnalyzer, TokenDebugger, OAuthValidator,
        ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo, OAuthConfig
    )
    from mcp.etdi.exceptions import ConfigurationError
    
    tests = []
    
    # Test 1: Invalid OAuth configuration
    try:
        invalid_config = OAuthConfig(
            provider="invalid-provider",
            client_id="",
            client_secret="",
            domain=""
        )
        
        validator = OAuthValidator()
        result = await validator.validate_provider("invalid", invalid_config)
        
        # Should fail configuration validation
        passed = not result.configuration_valid
        details = f"Config invalid as expected: {not result.configuration_valid}"
        tests.append(("Invalid OAuth configuration rejection", passed, details))
        
    except Exception as e:
        tests.append(("Invalid OAuth configuration rejection", False, str(e)))
    
    # Test 2: Malicious tool detection
    try:
        malicious_tool = ETDIToolDefinition(
            id="malicious-tool",
            name="Malicious Tool",
            version="0.1",  # Invalid version
            description="A tool with security issues",
            provider={"id": "", "name": ""},  # Missing provider
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
        )
        
        analyzer = SecurityAnalyzer()
        result = await analyzer.analyze_tool(malicious_tool)
        
        # Should have low security score and findings
        passed = result.overall_security_score < 30 and len(result.security_findings) > 0
        details = f"Security score: {result.overall_security_score:.1f}/100, Findings: {len(result.security_findings)}"
        tests.append(("Malicious tool detection", passed, details))
        
    except Exception as e:
        tests.append(("Malicious tool detection", False, str(e)))
    
    # Test 3: Invalid JWT token handling
    try:
        debugger = TokenDebugger()
        invalid_tokens = ["not.a.jwt", "invalid.jwt.token", "", "only-one-part"]
        
        all_detected = True
        for invalid_token in invalid_tokens:
            debug_info = debugger.debug_token(invalid_token)
            if debug_info.is_valid_jwt or len(debug_info.security_issues) == 0:
                all_detected = False
                break
        
        passed = all_detected
        details = f"All {len(invalid_tokens)} invalid tokens properly detected"
        tests.append(("Invalid JWT token detection", passed, details))
        
    except Exception as e:
        tests.append(("Invalid JWT token detection", False, str(e)))
    
    # Test 4: Unsupported OAuth provider handling
    try:
        from mcp.etdi import ETDIClient
        
        unsupported_config = {
            "security_level": "enhanced",
            "oauth_config": {
                "provider": "unsupported-provider",
                "client_id": "test",
                "client_secret": "test",
                "domain": "test.com"
            }
        }
        
        client = ETDIClient(unsupported_config)
        
        try:
            await client._setup_oauth_providers()
            passed = False  # Should have raised an exception
            details = "Should have raised ConfigurationError"
        except ConfigurationError:
            passed = True  # Expected exception
            details = "ConfigurationError raised as expected"
        except Exception as e:
            passed = False
            details = f"Unexpected exception: {e}"
        
        tests.append(("Unsupported OAuth provider rejection", passed, details))
        
    except Exception as e:
        tests.append(("Unsupported OAuth provider rejection", False, str(e)))
    
    # Test 5: Expired token detection
    try:
        debugger = TokenDebugger()
        # Token with past expiration time
        expired_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImV4cCI6MTYzNDU2NzAwMCwiaWF0IjoxNjM0NTY3MDAwfQ.signature"
        
        debug_info = debugger.debug_token(expired_token)
        
        # Should detect expiration
        is_expired = debug_info.expiration_info.get("is_expired", False)
        has_expiry_issue = any("expired" in issue.lower() for issue in debug_info.security_issues)
        
        passed = is_expired and has_expiry_issue
        details = f"Expired: {is_expired}, Has expiry issue: {has_expiry_issue}"
        tests.append(("Expired token detection", passed, details))
        
    except Exception as e:
        tests.append(("Expired token detection", False, str(e)))
    
    for test in tests:
        print_test(*test)
    
    return all(test[1] for test in tests)

async def test_edge_cases():
    """Test edge cases and boundary conditions"""
    print_section("Edge Case Tests")
    
    from mcp.etdi import SecurityAnalyzer, TokenDebugger
    
    tests = []
    
    # Test 1: Empty tool list handling
    try:
        analyzer = SecurityAnalyzer()
        results = await analyzer.analyze_multiple_tools([])
        
        passed = results == []
        details = f"Empty list returned: {results == []}"
        tests.append(("Empty tool list handling", passed, details))
        
    except Exception as e:
        tests.append(("Empty tool list handling", False, str(e)))
    
    # Test 2: Token comparison with identical tokens
    try:
        debugger = TokenDebugger()
        token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QifQ.sig"
        
        comparison = debugger.compare_tokens(token, token)
        
        passed = comparison["tokens_identical"] and len(comparison["differences"]) == 0
        details = f"Identical: {comparison['tokens_identical']}, Differences: {len(comparison['differences'])}"
        tests.append(("Identical token comparison", passed, details))
        
    except Exception as e:
        tests.append(("Identical token comparison", False, str(e)))
    
    # Test 3: Cache behavior
    try:
        from mcp.etdi import ETDIToolDefinition, Permission
        
        tool = ETDIToolDefinition(
            id="cache-test-tool",
            name="Cache Test Tool",
            version="1.0.0",
            description="Tool for cache testing",
            provider={"id": "test", "name": "Test"},
            schema={"type": "object"},
            permissions=[Permission(name="test", description="Test", scope="test", required=True)]
        )
        
        analyzer = SecurityAnalyzer()
        
        # First analysis
        result1 = await analyzer.analyze_tool(tool)
        
        # Second analysis (should use cache)
        result2 = await analyzer.analyze_tool(tool)
        
        # Clear cache
        analyzer.clear_cache()
        
        # Third analysis (fresh)
        result3 = await analyzer.analyze_tool(tool)
        
        passed = (result1.overall_security_score == result2.overall_security_score == result3.overall_security_score)
        details = f"Scores: {result1.overall_security_score:.1f}, {result2.overall_security_score:.1f}, {result3.overall_security_score:.1f}"
        tests.append(("Cache behavior consistency", passed, details))
        
    except Exception as e:
        tests.append(("Cache behavior consistency", False, str(e)))
    
    for test in tests:
        print_test(*test)
    
    return all(test[1] for test in tests)

async def test_cli_functionality():
    """Test CLI functionality"""
    print_section("CLI Functionality Tests")
    
    import subprocess
    import tempfile
    
    tests = []
    
    # Test 1: CLI help command
    try:
        result = subprocess.run([sys.executable, "-m", "mcp.etdi.cli", "--help"], 
                              capture_output=True, text=True, timeout=10)
        
        passed = result.returncode == 0 and "ETDI" in result.stdout
        details = f"Return code: {result.returncode}, Has ETDI: {'ETDI' in result.stdout}"
        tests.append(("CLI help command", passed, details))
        
    except Exception as e:
        tests.append(("CLI help command", False, str(e)))
    
    # Test 2: CLI config initialization
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test-config.json"
            
            result = subprocess.run([
                sys.executable, "-m", "mcp.etdi.cli", "init-config",
                "--output", str(config_file),
                "--provider", "auth0"
            ], capture_output=True, text=True, timeout=10)
            
            config_created = config_file.exists()
            if config_created:
                with open(config_file) as f:
                    config_data = json.load(f)
                has_oauth_config = "oauth_config" in config_data
            else:
                has_oauth_config = False
            
            passed = result.returncode == 0 and config_created and has_oauth_config
            details = f"Return code: {result.returncode}, Config created: {config_created}, Has OAuth: {has_oauth_config}"
            tests.append(("CLI config initialization", passed, details))
            
    except Exception as e:
        tests.append(("CLI config initialization", False, str(e)))
    
    # Test 3: CLI token debugging
    try:
        test_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QifQ.sig"
        
        result = subprocess.run([
            sys.executable, "-m", "mcp.etdi.cli", "debug-token",
            test_token, "--format", "json"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            try:
                output_data = json.loads(result.stdout)
                has_jwt_info = "is_valid_jwt" in output_data
            except json.JSONDecodeError:
                has_jwt_info = False
        else:
            has_jwt_info = False
        
        passed = result.returncode == 0 and has_jwt_info
        details = f"Return code: {result.returncode}, Has JWT info: {has_jwt_info}"
        tests.append(("CLI token debugging", passed, details))
        
    except Exception as e:
        tests.append(("CLI token debugging", False, str(e)))
    
    for test in tests:
        print_test(*test)
    
    return all(test[1] for test in tests)

def test_file_structure():
    """Test that all required files exist"""
    print_section("File Structure Tests")
    
    base_path = Path(__file__).parent.parent.parent  # Go up to python-sdk root
    required_files = [
        "src/mcp/etdi/__init__.py",
        "src/mcp/etdi/types.py",
        "src/mcp/etdi/exceptions.py",
        "src/mcp/etdi/oauth/__init__.py",
        "src/mcp/etdi/oauth/manager.py",
        "src/mcp/etdi/oauth/base.py",
        "src/mcp/etdi/oauth/auth0.py",
        "src/mcp/etdi/oauth/okta.py",
        "src/mcp/etdi/oauth/azure.py",
        "src/mcp/etdi/client/__init__.py",
        "src/mcp/etdi/client/etdi_client.py",
        "src/mcp/etdi/client/verifier.py",
        "src/mcp/etdi/client/approval_manager.py",
        "src/mcp/etdi/client/secure_session.py",
        "src/mcp/etdi/server/__init__.py",
        "src/mcp/etdi/server/secure_server.py",
        "src/mcp/etdi/server/middleware.py",
        "src/mcp/etdi/server/token_manager.py",
        "src/mcp/etdi/inspector/__init__.py",
        "src/mcp/etdi/inspector/security_analyzer.py",
        "src/mcp/etdi/inspector/token_debugger.py",
        "src/mcp/etdi/inspector/oauth_validator.py",
        "src/mcp/etdi/cli/__init__.py",
        "src/mcp/etdi/cli/etdi_cli.py",
        "examples/etdi/basic_usage.py",
        "examples/etdi/oauth_providers.py",
        "examples/etdi/secure_server_example.py",
        "examples/etdi/inspector_example.py",
        "tests/etdi/test_oauth_providers.py",
        "tests/etdi/test_etdi_client.py",
        "tests/etdi/test_inspector.py",
        "tests/etdi/test_integration.py",
        "INTEGRATION_GUIDE.md",
        "deployment/docker/Dockerfile",
        "deployment/docker/docker-compose.yml",
        "deployment/config/etdi-config.json"
    ]
    
    tests = []
    for file_path in required_files:
        full_path = base_path / file_path
        exists = full_path.exists()
        tests.append((f"File exists: {file_path}", exists))
    
    for test in tests:
        print_test(*test)
    
    # Assert that all files exist
    missing_files = [test[0] for test in tests if not test[1]]
    assert len(missing_files) == 0, f"Missing files: {missing_files}"

async def main():
    """Run all validation tests"""
    print("🚀 ETDI Implementation Validation")
    print("This script validates that ETDI works correctly with comprehensive tests.")
    
    test_results = []
    
    # Run all test suites
    test_results.append(("File Structure", test_file_structure()))
    test_results.append(("Basic Imports", await test_basic_imports()))
    test_results.append(("Positive Scenarios", await test_positive_scenarios()))
    test_results.append(("Negative Scenarios", await test_negative_scenarios()))
    test_results.append(("Edge Cases", await test_edge_cases()))
    test_results.append(("CLI Functionality", await test_cli_functionality()))
    
    # Print summary
    print_section("Test Summary")
    
    total_tests = len(test_results)
    passed_tests = sum(1 for _, passed in test_results if passed)
    
    for test_name, passed in test_results:
        print_test(test_name, passed)
    
    print(f"\n📊 Overall Results: {passed_tests}/{total_tests} test suites passed")
    
    if passed_tests == total_tests:
        print("\n🎉 All tests passed! ETDI implementation is working correctly.")
        print("\n✅ The implementation includes:")
        print("   • Positive tests (things that should work)")
        print("   • Negative tests (things that should fail safely)")
        print("   • Edge case handling")
        print("   • Error recovery")
        print("   • CLI functionality")
        print("   • Complete file structure")
        
        print("\n🚀 Next steps:")
        print("   1. Run: python3 setup_etdi.py")
        print("   2. Configure OAuth provider credentials")
        print("   3. Test with real OAuth providers")
        print("   4. Deploy using Docker or Kubernetes")
        
        return True
    else:
        print(f"\n❌ {total_tests - passed_tests} test suite(s) failed.")
        print("   Check the detailed output above for specific issues.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)