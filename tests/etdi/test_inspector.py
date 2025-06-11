"""
Tests for ETDI inspector tools
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from mcp.etdi.inspector import SecurityAnalyzer, TokenDebugger, OAuthValidator
from mcp.etdi import ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo, OAuthConfig
from mcp.etdi.exceptions import ETDIError


@pytest.fixture
def sample_tool():
    return ETDIToolDefinition(
        id="test-tool",
        name="Test Tool",
        version="1.0.0",
        description="A test tool",
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


@pytest.fixture
def insecure_tool():
    return ETDIToolDefinition(
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
        security=None  # No security
    )


@pytest.fixture
def oauth_config():
    return OAuthConfig(
        provider="auth0",
        client_id="test-client-id",
        client_secret="test-client-secret",
        domain="test.auth0.com",
        audience="https://test-api.example.com",
        scopes=["read:tools", "execute:tools"]
    )


class TestSecurityAnalyzer:
    """Test security analyzer functionality"""
    
    @pytest.mark.asyncio
    async def test_analyze_secure_tool(self, sample_tool):
        """Test analysis of a secure tool"""
        analyzer = SecurityAnalyzer()
        
        result = await analyzer.analyze_tool(sample_tool)
        
        assert result.tool_id == "test-tool"
        assert result.overall_security_score > 50  # Should have decent score
        assert result.permission_analysis.total_permissions == 1
        assert result.oauth_analysis is not None
        assert result.oauth_analysis.token_valid is False  # Can't validate without real OAuth
    
    @pytest.mark.asyncio
    async def test_analyze_insecure_tool(self, insecure_tool):
        """Test analysis of an insecure tool"""
        analyzer = SecurityAnalyzer()
        
        result = await analyzer.analyze_tool(insecure_tool)
        
        assert result.tool_id == "insecure-tool"
        assert result.overall_security_score < 50  # Should have low score
        assert len(result.security_findings) > 0
        
        # Check for specific security issues
        finding_messages = [f.message for f in result.security_findings]
        assert any("missing security" in msg.lower() for msg in finding_messages)
    
    @pytest.mark.asyncio
    async def test_analyze_multiple_tools(self, sample_tool, insecure_tool):
        """Test parallel analysis of multiple tools"""
        analyzer = SecurityAnalyzer()
        
        results = await analyzer.analyze_multiple_tools([sample_tool, insecure_tool])
        
        assert len(results) == 2
        assert results[0].tool_id in ["test-tool", "insecure-tool"]
        assert results[1].tool_id in ["test-tool", "insecure-tool"]
    
    def test_cache_functionality(self, sample_tool):
        """Test analyzer caching"""
        analyzer = SecurityAnalyzer()
        
        # Check initial cache state
        stats = analyzer.get_cache_stats()
        assert stats["cached_analyses"] == 0
        
        # Clear cache
        analyzer.clear_cache()
        stats = analyzer.get_cache_stats()
        assert stats["cached_analyses"] == 0


class TestTokenDebugger:
    """Test token debugger functionality"""
    
    def test_debug_valid_token(self):
        """Test debugging a valid JWT token"""
        debugger = TokenDebugger()
        
        # Sample JWT token (properly formatted but not cryptographically valid)
        import base64
        import json
        
        # Create a proper JWT structure
        header = {"typ": "JWT", "alg": "RS256", "kid": "test-key"}
        payload = {
            "iss": "https://test.auth0.com/",
            "sub": "test-tool",
            "aud": "https://test-api.example.com",
            "exp": 9999999999,
            "iat": 1634567000,
            "scope": "read:tools execute:tools",
            "tool_id": "test-tool",
            "tool_version": "1.0.0"
        }
        
        # Encode parts
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        signature_b64 = base64.urlsafe_b64encode(b"fake_signature").decode().rstrip('=')
        
        token = f"{header_b64}.{payload_b64}.{signature_b64}"
        
        debug_info = debugger.debug_token(token)
        
        assert debug_info.is_valid_jwt is True
        assert debug_info.header is not None
        assert debug_info.header.algorithm == "RS256"
        assert len(debug_info.claims) > 0
        
        # Check for ETDI compliance
        assert debug_info.etdi_compliance["has_tool_id"] is True
        assert debug_info.etdi_compliance["has_scopes"] is True
    
    def test_debug_invalid_token(self):
        """Test debugging an invalid token"""
        debugger = TokenDebugger()
        
        invalid_token = "not.a.valid.jwt"
        
        debug_info = debugger.debug_token(invalid_token)
        
        assert debug_info.is_valid_jwt is False
        assert len(debug_info.security_issues) > 0
        assert any("Invalid JWT format" in issue for issue in debug_info.security_issues)
    
    def test_compare_tokens(self):
        """Test token comparison functionality"""
        debugger = TokenDebugger()
        
        token1 = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImV4cCI6OTk5OTk5OTk5OX0.sig1"
        token2 = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6ImRpZmZlcmVudC10b29sIiwiZXhwIjo5OTk5OTk5OTk5fQ.sig2"
        
        comparison = debugger.compare_tokens(token1, token2)
        
        assert comparison["tokens_identical"] is False
        assert len(comparison["differences"]) > 0
        
        # Should find difference in subject
        sub_diff = next((d for d in comparison["differences"] if d["claim"] == "sub"), None)
        assert sub_diff is not None
        assert sub_diff["token1_value"] == "test-tool"
        assert sub_diff["token2_value"] == "different-tool"
    
    def test_extract_tool_info(self):
        """Test tool information extraction"""
        debugger = TokenDebugger()
        
        token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImF1ZCI6Imh0dHBzOi8vdGVzdC1hcGkuZXhhbXBsZS5jb20iLCJleHAiOjk5OTk5OTk5OTksInNjb3BlIjoicmVhZDpkYXRhIHdyaXRlOmRhdGEiLCJ0b29sX2lkIjoidGVzdC10b29sIiwidG9vbF92ZXJzaW9uIjoiMS4wLjAifQ.signature"
        
        tool_info = debugger.extract_tool_info(token)
        
        assert "error" not in tool_info
        assert tool_info["tool_id"] == "test-tool"
        assert tool_info["tool_version"] == "1.0.0"
        assert "read:data" in tool_info["permissions"]
        assert "write:data" in tool_info["permissions"]
    
    def test_format_debug_report(self):
        """Test debug report formatting"""
        debugger = TokenDebugger()
        
        token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InRlc3QtdG9vbCIsImV4cCI6OTk5OTk5OTk5OX0.signature"
        
        debug_info = debugger.debug_token(token)
        report = debugger.format_debug_report(debug_info)
        
        assert "ETDI OAuth Token Debug Report" in report
        assert "Valid JWT: True" in report
        assert "Algorithm: RS256" in report


class TestOAuthValidator:
    """Test OAuth validator functionality"""
    
    @pytest.mark.asyncio
    async def test_validate_configuration(self, oauth_config):
        """Test OAuth configuration validation"""
        validator = OAuthValidator()
        
        result = await validator.validate_provider("auth0", oauth_config)
        
        assert result.provider_name == "auth0"
        assert result.configuration_valid is True
        
        # Check for configuration validation checks
        config_checks = [c for c in result.checks if "client_id" in c.name or "domain" in c.name]
        assert len(config_checks) > 0
    
    @pytest.mark.asyncio
    async def test_validate_invalid_configuration(self):
        """Test validation of invalid configuration"""
        validator = OAuthValidator()
        
        invalid_config = OAuthConfig(
            provider="auth0",
            client_id="",  # Missing client ID
            client_secret="",  # Missing client secret
            domain=""  # Missing domain
        )
        
        result = await validator.validate_provider("auth0", invalid_config)
        
        assert result.configuration_valid is False
        
        # Check for specific validation failures
        failed_checks = [c for c in result.checks if not c.passed]
        assert len(failed_checks) > 0
        
        error_messages = [c.message for c in failed_checks]
        assert any("Client ID is required" in msg for msg in error_messages)
    
    @pytest.mark.asyncio
    async def test_etdi_compliance_validation(self, sample_tool):
        """Test ETDI compliance validation"""
        validator = OAuthValidator()
        
        report = await validator.validate_etdi_compliance(sample_tool)
        
        assert report.tool_id == "test-tool"
        assert report.overall_compliance > 0
        assert report.oauth_compliance > 0
        assert len(report.checks) > 0
    
    @pytest.mark.asyncio
    async def test_etdi_compliance_insecure_tool(self, insecure_tool):
        """Test ETDI compliance validation for insecure tool"""
        validator = OAuthValidator()
        
        report = await validator.validate_etdi_compliance(insecure_tool)
        
        assert report.tool_id == "insecure-tool"
        assert report.overall_compliance < 50  # Should have low compliance
        
        # Check for specific compliance failures
        failed_checks = [c for c in report.checks if not c.passed]
        assert len(failed_checks) > 0
        
        # Should have recommendations
        assert len(report.recommendations) > 0
    
    @pytest.mark.asyncio
    async def test_batch_validate_providers(self, oauth_config):
        """Test batch provider validation"""
        validator = OAuthValidator()
        
        providers = {
            "auth0": oauth_config,
            "invalid": OAuthConfig(provider="invalid", client_id="", client_secret="", domain="")
        }
        
        results = await validator.batch_validate_providers(providers)
        
        assert len(results) == 2
        assert "auth0" in results
        assert "invalid" in results
        
        # Auth0 should have valid config, invalid should not
        assert results["auth0"].configuration_valid is True
        assert results["invalid"].configuration_valid is False
    
    def test_cache_functionality(self):
        """Test validator caching"""
        validator = OAuthValidator()
        
        # Check initial cache state
        stats = validator.get_cache_stats()
        assert stats["cached_validations"] == 0
        
        # Clear cache
        validator.clear_cache()
        stats = validator.get_cache_stats()
        assert stats["cached_validations"] == 0


@pytest.mark.asyncio
async def test_inspector_integration(sample_tool, oauth_config):
    """Test integration between inspector tools"""
    # Create all inspector tools
    analyzer = SecurityAnalyzer()
    debugger = TokenDebugger()
    validator = OAuthValidator()
    
    # Analyze tool security
    security_result = await analyzer.analyze_tool(sample_tool)
    
    # Debug the OAuth token
    if sample_tool.security and sample_tool.security.oauth:
        debug_info = debugger.debug_token(sample_tool.security.oauth.token)
        
        # Validate ETDI compliance
        compliance_report = await validator.validate_etdi_compliance(sample_tool)
        
        # All tools should provide consistent information
        assert security_result.tool_id == sample_tool.id
        assert debug_info.is_valid_jwt is True
        assert compliance_report.tool_id == sample_tool.id
        
        # Security score and compliance should be related
        # (both should be reasonable for a well-configured tool)
        assert security_result.overall_security_score > 30
        assert compliance_report.overall_compliance > 30


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling in inspector tools"""
    analyzer = SecurityAnalyzer()
    debugger = TokenDebugger()
    validator = OAuthValidator()
    
    # Test with None/invalid inputs
    with pytest.raises(Exception):
        await analyzer.analyze_tool(None)
    
    # Test with malformed token
    debug_info = debugger.debug_token("malformed")
    assert debug_info.is_valid_jwt is False
    
    # Test with invalid config
    invalid_config = OAuthConfig(provider="", client_id="", client_secret="", domain="")
    result = await validator.validate_provider("invalid", invalid_config)
    assert result.configuration_valid is False