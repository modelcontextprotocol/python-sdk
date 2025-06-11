"""
Comprehensive integration tests for ETDI - both positive and negative scenarios
"""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from mcp.etdi import (
    ETDIClient, SecurityAnalyzer, TokenDebugger, OAuthValidator,
    ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo, OAuthConfig,
    SecurityLevel, VerificationStatus
)
# Import ETDISecureServer directly to avoid circular dependency
from mcp.etdi.server.secure_server import ETDISecureServer
from mcp.etdi.oauth import Auth0Provider
from mcp.etdi.exceptions import ETDIError, OAuthError, PermissionError, ConfigurationError


class TestETDIIntegration:
    """Integration tests covering positive and negative scenarios"""
    
    @pytest.fixture
    def valid_oauth_config(self):
        return OAuthConfig(
            provider="auth0",
            client_id="test-client-id",
            client_secret="test-client-secret",
            domain="test.auth0.com",
            audience="https://test-api.example.com",
            scopes=["read:tools", "execute:tools"]
        )
    
    @pytest.fixture
    def invalid_oauth_config(self):
        return OAuthConfig(
            provider="invalid-provider",
            client_id="",
            client_secret="",
            domain="",
            audience=""
        )
    
    @pytest.fixture
    def valid_tool(self):
        return ETDIToolDefinition(
            id="test-tool",
            name="Test Tool",
            version="1.0.0",
            description="A valid test tool",
            provider={"id": "test-provider", "name": "Test Provider"},
            schema={"type": "object", "properties": {"param": {"type": "string"}}},
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
    
    @pytest.fixture
    def malicious_tool(self):
        """Tool with security issues for negative testing"""
        return ETDIToolDefinition(
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
                    token="invalid.jwt.token",  # Invalid token
                    provider="unknown-provider"
                )
            )
        )


class TestPositiveScenarios:
    """Test positive scenarios - things that should work"""
    
    @pytest.mark.asyncio
    async def test_valid_oauth_configuration(self, valid_oauth_config):
        """Test that valid OAuth configuration works"""
        validator = OAuthValidator()
        
        # This should pass configuration validation
        result = await validator.validate_provider("auth0", valid_oauth_config)
        
        assert result.configuration_valid is True
        assert result.provider_name == "auth0"
        
        # Check that all required configuration checks pass
        config_checks = [c for c in result.checks if c.name.startswith("client_id") or c.name.startswith("domain")]
        passed_checks = [c for c in config_checks if c.passed]
        assert len(passed_checks) > 0
    
    @pytest.mark.asyncio
    async def test_valid_tool_security_analysis(self, valid_tool):
        """Test that valid tools get good security scores"""
        analyzer = SecurityAnalyzer()
        
        result = await analyzer.analyze_tool(valid_tool)
        
        # Valid tool should have decent security score
        assert result.overall_security_score > 50
        assert result.tool_id == "valid-tool"
        assert result.permission_analysis.total_permissions == 1
        
        # Should have OAuth analysis
        assert result.oauth_analysis is not None
        
        # Should have minimal critical findings
        critical_findings = [f for f in result.security_findings if f.severity.value == "critical"]
        assert len(critical_findings) == 0
    
    @pytest.mark.asyncio
    async def test_valid_jwt_token_debugging(self):
        """Test that valid JWT tokens are properly analyzed"""
        debugger = TokenDebugger()
        
        # Valid JWT token (structure-wise)
        valid_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5In0.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksImlhdCI6MTYzNDU2NzAwMCwic2NvcGUiOiJyZWFkOnRvb2xzIGV4ZWN1dGU6dG9vbHMiLCJ0b29sX2lkIjoidGVzdC10b29sIiwidG9vbF92ZXJzaW9uIjoiMS4wLjAifQ.signature"
        
        debug_info = debugger.debug_token(valid_token)
        
        # Should successfully parse the token
        assert debug_info.is_valid_jwt is True
        assert debug_info.header is not None
        assert debug_info.header.algorithm == "RS256"
        assert len(debug_info.claims) > 0
        
        # Should have good ETDI compliance
        assert debug_info.etdi_compliance["has_tool_id"] is True
        assert debug_info.etdi_compliance["has_scopes"] is True
        assert debug_info.etdi_compliance["compliance_score"] > 60
    
    @pytest.mark.asyncio
    async def test_etdi_client_initialization(self, valid_oauth_config):
        """Test that ETDI client initializes correctly with valid config"""
        config = {
            "security_level": "enhanced",
            "oauth_config": valid_oauth_config.to_dict(),
            "allow_non_etdi_tools": True,
            "show_unverified_tools": False
        }
        
        client = ETDIClient(config)
        
        # Should initialize without errors
        with patch.object(client, '_setup_oauth_providers') as mock_setup:
            mock_setup.return_value = None
            await client.initialize()
            
            assert client._initialized is True
            mock_setup.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_tool_approval_workflow(self, valid_tool):
        """Test complete tool approval workflow"""
        from mcp.etdi.client import ApprovalManager
        
        with tempfile.TemporaryDirectory() as temp_dir:
            approval_manager = ApprovalManager(storage_path=temp_dir)
            
            # Tool should not be approved initially
            is_approved = await approval_manager.is_tool_approved(valid_tool.id)
            assert is_approved is False
            
            # Approve the tool
            record = await approval_manager.approve_tool_with_etdi(valid_tool)
            
            # Should now be approved
            is_approved = await approval_manager.is_tool_approved(valid_tool.id)
            assert is_approved is True
            
            # Should be able to retrieve approval
            retrieved_approval = await approval_manager.get_approval(valid_tool.id)
            assert retrieved_approval is not None
            assert retrieved_approval.tool_id == valid_tool.id


class TestNegativeScenarios:
    """Test negative scenarios - things that should fail safely"""
    
    @pytest.mark.asyncio
    async def test_invalid_oauth_configuration(self, invalid_oauth_config):
        """Test that invalid OAuth configuration is properly rejected"""
        validator = OAuthValidator()
        
        result = await validator.validate_provider("invalid", invalid_oauth_config)
        
        # Should fail configuration validation
        assert result.configuration_valid is False
        assert result.provider_name == "invalid"
        
        # Should have multiple failed checks
        failed_checks = [c for c in result.checks if not c.passed]
        assert len(failed_checks) > 0
        
        # Should identify missing client ID and secret
        error_messages = [c.message for c in failed_checks]
        assert any("Client ID is required" in msg for msg in error_messages)
        assert any("Client secret is required" in msg for msg in error_messages)
    
    @pytest.mark.asyncio
    async def test_malicious_tool_detection(self, malicious_tool):
        """Test that malicious/insecure tools are properly detected"""
        analyzer = SecurityAnalyzer()
        
        result = await analyzer.analyze_tool(malicious_tool)
        
        # Should have low security score
        assert result.overall_security_score < 30
        
        # Should have multiple security findings
        assert len(result.security_findings) > 0
        
        # Should detect specific issues
        finding_messages = [f.message for f in result.security_findings]
        assert any("missing security" in msg.lower() for msg in finding_messages)
        
        # Should have recommendations
        assert len(result.recommendations) > 0
    
    def test_invalid_jwt_token_handling(self):
        """Test that invalid JWT tokens are properly handled"""
        debugger = TokenDebugger()
        
        # Test various invalid token formats
        invalid_tokens = [
            "not.a.jwt",
            "invalid.jwt.token",
            "",
            "only-one-part",
            "too.many.parts.here.invalid"
        ]
        
        for invalid_token in invalid_tokens:
            debug_info = debugger.debug_token(invalid_token)
            
            # Should detect as invalid
            assert debug_info.is_valid_jwt is False
            
            # Should have security issues
            assert len(debug_info.security_issues) > 0
            
            # Should have recommendations
            assert len(debug_info.recommendations) > 0
    
    @pytest.mark.asyncio
    async def test_etdi_client_invalid_config(self):
        """Test ETDI client with invalid configuration"""
        # Missing OAuth config for enhanced security
        invalid_config = {
            "security_level": "enhanced",
            "oauth_config": None  # Missing required OAuth config
        }
        
        client = ETDIClient(invalid_config)
        
        # Should fail during OAuth setup
        with pytest.raises(ConfigurationError):
            await client._setup_oauth_providers()
    
    @pytest.mark.asyncio
    async def test_unsupported_oauth_provider(self):
        """Test handling of unsupported OAuth providers"""
        unsupported_config = OAuthConfig(
            provider="unsupported-provider",
            client_id="test",
            client_secret="test",
            domain="test.com"
        )
        
        client_config = {
            "security_level": "enhanced",
            "oauth_config": unsupported_config.to_dict()
        }
        
        client = ETDIClient(client_config)
        
        # Should raise configuration error for unsupported provider
        with pytest.raises(ConfigurationError) as exc_info:
            await client._setup_oauth_providers()
        
        assert "Unsupported OAuth provider" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_tool_approval_with_invalid_tool(self):
        """Test tool approval with invalid/malicious tool"""
        from mcp.etdi.client import ApprovalManager
        
        # Tool without security information
        insecure_tool = ETDIToolDefinition(
            id="insecure-tool",
            name="Insecure Tool",
            version="1.0.0",
            description="Tool without security",
            provider={"id": "test", "name": "Test"},
            schema={"type": "object"},
            permissions=[],
            security=None  # No security
        )
        
        with tempfile.TemporaryDirectory() as temp_dir:
            approval_manager = ApprovalManager(storage_path=temp_dir)
            
            # Should be able to approve even insecure tools (with warnings)
            # This tests that the system doesn't crash on edge cases
            record = await approval_manager.approve_tool_with_etdi(insecure_tool)
            assert record.tool_id == "insecure-tool"
    
    @pytest.mark.asyncio
    async def test_token_validation_with_mismatched_claims(self):
        """Test token validation with mismatched tool claims"""
        from mcp.etdi.oauth import Auth0Provider
        
        config = OAuthConfig(
            provider="auth0",
            client_id="test",
            client_secret="test",
            domain="test.auth0.com"
        )
        
        provider = Auth0Provider(config)
        await provider.initialize()
        
        # Token with mismatched tool ID
        token_with_wrong_tool_id = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6Indyb25nLXRvb2wtaWQiLCJhdWQiOiJodHRwczovL3Rlc3QtYXBpLmV4YW1wbGUuY29tIiwiZXhwIjo5OTk5OTk5OTk5LCJ0b29sX2lkIjoid3JvbmctdG9vbC1pZCJ9.signature"
        
        expected_claims = {
            "toolId": "correct-tool-id",
            "toolVersion": "1.0.0"
        }
        
        # Mock the JWT verification to focus on tool ID validation
        with patch.object(provider, '_verify_jwt_signature') as mock_verify:
            mock_verify.return_value = {
                "iss": "https://test.auth0.com/",
                "sub": "wrong-tool-id",
                "aud": "https://test-api.example.com",
                "exp": 9999999999,
                "tool_id": "wrong-tool-id"
            }
            
            result = await provider.validate_token(token_with_wrong_tool_id, expected_claims)
        
        # Should fail validation due to tool ID mismatch
        assert result.valid is False
        assert "tool_id mismatch" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_expired_token_detection(self):
        """Test detection of expired tokens"""
        debugger = TokenDebugger()
        
        # Token with past expiration time
        expired_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImV4cCI6MTYzNDU2NzAwMCwiaWF0IjoxNjM0NTY3MDAwfQ.signature"
        
        debug_info = debugger.debug_token(expired_token)
        
        # Should detect expiration
        assert debug_info.expiration_info.get("is_expired") is True
        
        # Should have security issues about expiration
        assert any("expired" in issue.lower() for issue in debug_info.security_issues)
        
        # Should recommend token refresh
        assert any("refresh" in rec.lower() for rec in debug_info.recommendations)


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    @pytest.mark.asyncio
    async def test_empty_tool_list_handling(self):
        """Test handling of empty tool lists"""
        analyzer = SecurityAnalyzer()
        
        # Should handle empty list gracefully
        results = await analyzer.analyze_multiple_tools([])
        assert results == []
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_analysis(self, valid_tool, malicious_tool):
        """Test concurrent analysis of multiple tools"""
        analyzer = SecurityAnalyzer()
        
        # Analyze multiple tools concurrently
        tools = [valid_tool, malicious_tool] * 5  # 10 tools total
        results = await analyzer.analyze_multiple_tools(tools)
        
        # Should get results for all tools
        assert len(results) == 10
        
        # Should have mix of good and bad scores
        scores = [r.overall_security_score for r in results]
        assert max(scores) > 50  # Some good scores
        assert min(scores) < 30  # Some bad scores
    
    @pytest.mark.asyncio
    async def test_cache_behavior(self, valid_tool):
        """Test caching behavior in security analyzer"""
        analyzer = SecurityAnalyzer()
        
        # First analysis
        result1 = await analyzer.analyze_tool(valid_tool)
        
        # Second analysis should use cache
        result2 = await analyzer.analyze_tool(valid_tool)
        
        # Results should be identical
        assert result1.overall_security_score == result2.overall_security_score
        assert result1.tool_id == result2.tool_id
        
        # Clear cache and analyze again
        analyzer.clear_cache()
        result3 = await analyzer.analyze_tool(valid_tool)
        
        # Should still get same results (but computed fresh)
        assert result3.overall_security_score == result1.overall_security_score
    
    def test_token_comparison_edge_cases(self):
        """Test token comparison with edge cases"""
        debugger = TokenDebugger()
        
        # Compare identical tokens
        token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QifQ.sig"
        
        comparison = debugger.compare_tokens(token, token)
        assert comparison["tokens_identical"] is True
        assert len(comparison["differences"]) == 0
        
        # Compare with invalid token
        invalid_token = "invalid"
        
        comparison = debugger.compare_tokens(token, invalid_token)
        assert comparison["tokens_identical"] is False
        # Should handle gracefully without crashing


class TestErrorRecovery:
    """Test error recovery and resilience"""
    
    @pytest.mark.asyncio
    async def test_network_failure_handling(self):
        """Test handling of network failures during OAuth validation"""
        validator = OAuthValidator()
        
        config = OAuthConfig(
            provider="auth0",
            client_id="test",
            client_secret="test",
            domain="nonexistent-domain-12345.auth0.com"  # Non-existent domain
        )
        
        # Should handle network failure gracefully
        result = await validator.validate_provider("auth0", config, timeout=1.0)
        
        # Should fail but not crash
        assert result.is_reachable is False
        assert len(result.checks) > 0
        
        # Should have appropriate error messages
        failed_checks = [c for c in result.checks if not c.passed]
        assert len(failed_checks) > 0
    
    @pytest.mark.asyncio
    async def test_corrupted_approval_storage(self):
        """Test handling of corrupted approval storage"""
        from mcp.etdi.client import ApprovalManager
        
        with tempfile.TemporaryDirectory() as temp_dir:
            approval_manager = ApprovalManager(storage_path=temp_dir)
            
            # Create corrupted approval file
            corrupted_file = Path(temp_dir) / "corrupted.approval"
            with open(corrupted_file, 'wb') as f:
                f.write(b"corrupted data")
            
            # Should handle corrupted files gracefully
            approvals = await approval_manager.list_approvals()
            # Should return empty list, not crash
            assert isinstance(approvals, list)


def test_comprehensive_validation():
    """Comprehensive validation test that exercises multiple components"""
    
    # Test data setup
    valid_config = OAuthConfig(
        provider="auth0",
        client_id="test-client",
        client_secret="test-secret",
        domain="test.auth0.com"
    )
    
    valid_tool = ETDIToolDefinition(
        id="comprehensive-test-tool",
        name="Comprehensive Test Tool",
        version="1.0.0",
        description="Tool for comprehensive testing",
        provider={"id": "test", "name": "Test Provider"},
        schema={"type": "object"},
        permissions=[
            Permission(name="test", description="Test permission", scope="test:read", required=True)
        ],
        security=SecurityInfo(
            oauth=OAuthInfo(token="valid.jwt.token", provider="auth0")
        )
    )
    
    # Test all components work together
    debugger = TokenDebugger()
    
    # Should handle the tool's token
    debug_info = debugger.debug_token(valid_tool.security.oauth.token)
    assert debug_info is not None
    
    # Should generate readable report
    report = debugger.format_debug_report(debug_info)
    assert "ETDI OAuth Token Debug Report" in report
    
    print("✅ Comprehensive validation passed")


if __name__ == "__main__":
    # Run a quick validation
    test_comprehensive_validation()
    print("✅ All validation tests can be run with: pytest tests/etdi/test_integration.py -v")