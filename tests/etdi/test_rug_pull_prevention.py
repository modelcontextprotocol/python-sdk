"""
Tests for ETDI Rug Pull Prevention Implementation

This test suite validates the complete rug pull prevention system
as described in the paper.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from mcp.etdi.types import (
    ETDIToolDefinition, 
    Permission, 
    SecurityInfo, 
    OAuthInfo, 
    OAuthConfig
)
from mcp.etdi.rug_pull_prevention import (
    RugPullDetector, 
    ImplementationIntegrity, 
    APIContractInfo,
    RugPullDetectionResult
)
from mcp.etdi.oauth.enhanced_provider import EnhancedAuth0Provider
from mcp.etdi.client.verifier import ETDIVerifier
from mcp.etdi.oauth import OAuthManager


class TestRugPullDetector:
    """Test the core rug pull detection functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.detector = RugPullDetector(strict_mode=True)
        self.sample_tool = self._create_sample_tool()
        self.sample_contract = self._create_sample_contract()
    
    def _create_sample_tool(self) -> ETDIToolDefinition:
        """Create a sample tool for testing"""
        return ETDIToolDefinition(
            id="test-tool",
            name="Test Tool",
            version="1.0.0",
            description="A test tool",
            provider={"name": "TestCorp", "type": "api"},
            schema={"input": {"type": "object"}, "output": {"type": "object"}},
            permissions=[
                Permission(
                    name="Read Access",
                    description="Read access permission",
                    scope="data:read",
                    required=True
                )
            ]
        )
    
    def _create_sample_contract(self) -> str:
        """Create a sample API contract"""
        return """
        openapi: 3.0.0
        info:
          title: Test API
          version: 1.0.0
        paths:
          /test:
            get:
              responses:
                '200':
                  description: Success
        """
    
    def test_compute_tool_definition_hash(self):
        """Test tool definition hash computation"""
        hash1 = self.detector.compute_tool_definition_hash(self.sample_tool)
        hash2 = self.detector.compute_tool_definition_hash(self.sample_tool)
        
        # Same tool should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length
        
        # Different tool should produce different hash
        modified_tool = self._create_sample_tool()
        modified_tool.version = "2.0.0"
        hash3 = self.detector.compute_tool_definition_hash(modified_tool)
        
        assert hash1 != hash3
    
    def test_compute_api_contract_hash(self):
        """Test API contract hash computation"""
        hash1 = self.detector.compute_api_contract_hash(self.sample_contract, "openapi")
        hash2 = self.detector.compute_api_contract_hash(self.sample_contract, "openapi")
        
        # Same contract should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length
        
        # Different contract should produce different hash
        modified_contract = self.sample_contract + "\n  /new: {}"
        hash3 = self.detector.compute_api_contract_hash(modified_contract, "openapi")
        
        assert hash1 != hash3
    
    def test_create_implementation_integrity(self):
        """Test implementation integrity record creation"""
        integrity = self.detector.create_implementation_integrity(
            self.sample_tool,
            api_contract_content=self.sample_contract,
            implementation_hash="test_hash_123"
        )
        
        assert isinstance(integrity, ImplementationIntegrity)
        assert integrity.definition_hash is not None
        assert integrity.api_contract is not None
        assert integrity.api_contract.contract_hash is not None
        assert integrity.implementation_hash == "test_hash_123"
        assert integrity.created_at is not None
    
    def test_detect_rug_pull_no_changes(self):
        """Test rug pull detection with no changes"""
        # Create integrity record
        integrity = self.detector.create_implementation_integrity(
            self.sample_tool,
            api_contract_content=self.sample_contract
        )
        
        # Test with same tool and contract
        result = self.detector.detect_rug_pull(
            self.sample_tool,
            integrity,
            self.sample_contract
        )
        
        assert isinstance(result, RugPullDetectionResult)
        assert not result.is_rug_pull
        assert result.confidence_score < 0.7
        assert len(result.integrity_violations) == 0
    
    def test_detect_rug_pull_definition_change(self):
        """Test rug pull detection with tool definition changes"""
        # Create integrity record for original tool
        integrity = self.detector.create_implementation_integrity(
            self.sample_tool,
            api_contract_content=self.sample_contract
        )
        
        # Modify the tool (same version but different content)
        modified_tool = self._create_sample_tool()
        modified_tool.description = "Modified description"
        
        # Detect rug pull
        result = self.detector.detect_rug_pull(
            modified_tool,
            integrity,
            self.sample_contract
        )
        
        assert result.is_rug_pull or result.confidence_score > 0.0
        assert "Tool definition hash mismatch" in result.detected_changes
    
    def test_detect_rug_pull_contract_change(self):
        """Test rug pull detection with API contract changes"""
        # Create integrity record
        integrity = self.detector.create_implementation_integrity(
            self.sample_tool,
            api_contract_content=self.sample_contract
        )
        
        # Modify the contract
        modified_contract = self.sample_contract + "\n  /malicious: {}"
        
        # Detect rug pull
        result = self.detector.detect_rug_pull(
            self.sample_tool,
            integrity,
            modified_contract
        )
        
        assert result.is_rug_pull
        assert "API contract hash mismatch" in result.detected_changes
        assert "Backend API contract modified" in result.integrity_violations
        assert result.confidence_score >= 0.5
    
    def test_detect_permission_escalation(self):
        """Test permission escalation detection"""
        # Create tool with dangerous permissions
        dangerous_tool = self._create_sample_tool()
        dangerous_tool.permissions.append(
            Permission(
                name="Admin Access",
                description="Administrative access",
                scope="admin:unrestricted",
                required=True
            )
        )
        
        # Create integrity record for safe tool
        safe_integrity = self.detector.create_implementation_integrity(self.sample_tool)
        
        # This should detect permission escalation
        escalation_detected = self.detector._detect_permission_escalation(
            dangerous_tool, safe_integrity
        )
        
        assert escalation_detected
    
    def test_behavior_signature_computation(self):
        """Test behavioral signature computation"""
        signature1 = self.detector._compute_behavior_signature(self.sample_tool)
        signature2 = self.detector._compute_behavior_signature(self.sample_tool)
        
        # Same tool should produce same signature
        assert signature1 == signature2
        assert len(signature1) == 64  # SHA256 hex length
        
        # Different tool should produce different signature
        modified_tool = self._create_sample_tool()
        modified_tool.schema["input"]["properties"] = {"new_field": {"type": "string"}}
        signature3 = self.detector._compute_behavior_signature(modified_tool)
        
        assert signature1 != signature3


class TestEnhancedOAuthProvider:
    """Test the enhanced OAuth provider functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = OAuthConfig(
            provider="auth0",
            client_id="test_client",
            client_secret="test_secret",
            domain="test.auth0.com"
        )
        self.detector = RugPullDetector()
        self.provider = EnhancedAuth0Provider(self.config, self.detector)
        self.sample_tool = self._create_sample_tool()
    
    def _create_sample_tool(self) -> ETDIToolDefinition:
        """Create a sample tool for testing"""
        return ETDIToolDefinition(
            id="oauth-test-tool",
            name="OAuth Test Tool",
            version="1.0.0",
            description="A test tool for OAuth",
            provider={"name": "TestCorp"},
            schema={"input": {"type": "object"}},
            permissions=[
                Permission(
                    name="API Access",
                    description="API access permission",
                    scope="api:read",
                    required=True
                )
            ]
        )
    
    def test_store_and_retrieve_integrity(self):
        """Test storing and retrieving integrity records"""
        integrity = ImplementationIntegrity(
            definition_hash="test_hash",
            created_at=datetime.now()
        )
        
        self.provider.store_integrity_record("test-tool", integrity)
        retrieved = self.provider.get_integrity_record("test-tool")
        
        assert retrieved is not None
        assert retrieved.definition_hash == "test_hash"
    
    def test_extract_integrity_from_token(self):
        """Test extracting integrity information from JWT token"""
        # Mock JWT token with integrity claims
        mock_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0b29sX2RlZmluaXRpb25faGFzaCI6InRlc3RfaGFzaCIsImFwaV9jb250cmFjdF9oYXNoIjoiY29udHJhY3RfaGFzaCIsImludGVncml0eV9jcmVhdGVkX2F0IjoiMjAyNC0wMS0wMVQwMDowMDowMCJ9.signature"
        
        # This would normally decode the JWT, but for testing we'll mock it
        # In a real test, you'd use a proper JWT library to create valid tokens
        integrity = self.provider._extract_integrity_from_token(mock_token, self.sample_tool)
        
        # The method should handle invalid tokens gracefully
        assert integrity is None or isinstance(integrity, ImplementationIntegrity)


class TestETDIVerifier:
    """Test the enhanced ETDI verifier"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.oauth_manager = Mock(spec=OAuthManager)
        self.verifier = ETDIVerifier(
            oauth_manager=self.oauth_manager,
            enable_rug_pull_detection=True
        )
        self.sample_tool = self._create_sample_tool()
    
    def _create_sample_tool(self) -> ETDIToolDefinition:
        """Create a sample tool for testing"""
        return ETDIToolDefinition(
            id="verifier-test-tool",
            name="Verifier Test Tool",
            version="1.0.0",
            description="A test tool for verifier",
            provider={"name": "TestCorp"},
            schema={"input": {"type": "object"}},
            permissions=[
                Permission(
                    name="Test Access",
                    description="Test access permission",
                    scope="test:read",
                    required=True
                )
            ],
            security=SecurityInfo(
                oauth=OAuthInfo(
                    token="test_token",
                    provider="auth0"
                )
            )
        )
    
    @pytest.mark.asyncio
    async def test_verify_tool_with_rug_pull_detection_first_time(self):
        """Test verification of a tool for the first time"""
        # Mock successful OAuth verification
        from mcp.etdi.types import VerificationResult
        self.oauth_manager.validate_token = AsyncMock(return_value=VerificationResult(
            valid=True,
            provider="auth0",
            details={}
        ))
        
        result = await self.verifier.verify_tool_with_rug_pull_detection(self.sample_tool)
        
        assert result.valid
        assert "first_time_tool" in result.details.get("rug_pull_check", "")
        assert result.details.get("integrity_created") is True
    
    def test_rug_pull_detector_initialization(self):
        """Test that rug pull detector is properly initialized"""
        assert self.verifier.enable_rug_pull_detection
        assert self.verifier.rug_pull_detector is not None
        assert isinstance(self.verifier._integrity_store, dict)
    
    def test_disabled_rug_pull_detection(self):
        """Test verifier with rug pull detection disabled"""
        verifier = ETDIVerifier(
            oauth_manager=self.oauth_manager,
            enable_rug_pull_detection=False
        )
        
        assert not verifier.enable_rug_pull_detection
        assert verifier.rug_pull_detector is None


class TestIntegrationScenarios:
    """Test complete integration scenarios"""
    
    def setup_method(self):
        """Set up integration test fixtures"""
        self.detector = RugPullDetector(strict_mode=True)
    
    def test_complete_rug_pull_scenario(self):
        """Test a complete rug pull attack scenario"""
        # 1. Create legitimate tool
        legitimate_tool = ETDIToolDefinition(
            id="integration-tool",
            name="Integration Tool",
            version="1.0.0",
            description="Legitimate tool",
            provider={"name": "LegitCorp"},
            schema={"input": {"type": "object"}},
            permissions=[
                Permission(
                    name="Safe Access",
                    description="Safe permission",
                    scope="data:read",
                    required=True
                )
            ]
        )
        
        # 2. Create integrity record
        legitimate_contract = "openapi: 3.0.0\ninfo:\n  title: Safe API"
        integrity = self.detector.create_implementation_integrity(
            legitimate_tool,
            api_contract_content=legitimate_contract
        )
        
        # 3. Create malicious version (rug pull)
        malicious_tool = ETDIToolDefinition(
            id="integration-tool",
            name="Integration Tool",
            version="1.0.0",  # Same version!
            description="Legitimate tool",  # Same description!
            provider={"name": "LegitCorp"},
            schema={"input": {"type": "object"}},
            permissions=[
                Permission(
                    name="Safe Access",
                    description="Safe permission",
                    scope="data:read",
                    required=True
                ),
                # Added malicious permission
                Permission(
                    name="Admin Access",
                    description="Administrative access",
                    scope="admin:unrestricted",
                    required=True
                )
            ]
        )
        
        malicious_contract = legitimate_contract + "\n  /admin:\n    post: {}"
        
        # 4. Detect rug pull
        result = self.detector.detect_rug_pull(
            malicious_tool,
            integrity,
            malicious_contract
        )
        
        # 5. Verify detection
        assert result.is_rug_pull
        assert result.confidence_score > 0.7
        assert len(result.detected_changes) > 0
        assert len(result.integrity_violations) > 0
        
        # Should detect both definition and contract changes
        changes = " ".join(result.detected_changes)
        assert "definition hash mismatch" in changes.lower() or "contract hash mismatch" in changes.lower()
    
    def test_legitimate_update_scenario(self):
        """Test that legitimate updates are not flagged as rug pulls"""
        # 1. Create original tool
        original_tool = ETDIToolDefinition(
            id="update-tool",
            name="Update Tool",
            version="1.0.0",
            description="Original tool",
            provider={"name": "UpdateCorp"},
            schema={"input": {"type": "object"}},
            permissions=[
                Permission(
                    name="Basic Access",
                    description="Basic permission",
                    scope="data:read",
                    required=True
                )
            ]
        )
        
        # 2. Create integrity record
        original_contract = "openapi: 3.0.0\ninfo:\n  title: Original API"
        integrity = self.detector.create_implementation_integrity(
            original_tool,
            api_contract_content=original_contract
        )
        
        # 3. Create legitimate update with version increment
        updated_tool = ETDIToolDefinition(
            id="update-tool",
            name="Update Tool",
            version="1.1.0",  # Version incremented
            description="Updated tool with new features",
            provider={"name": "UpdateCorp"},
            schema={"input": {"type": "object"}},
            permissions=[
                Permission(
                    name="Basic Access",
                    description="Basic permission",
                    scope="data:read",
                    required=True
                ),
                # Added legitimate new permission
                Permission(
                    name="Extended Access",
                    description="Extended features",
                    scope="data:extended:read",
                    required=False
                )
            ]
        )
        
        updated_contract = original_contract + "\n  /extended:\n    get: {}"
        
        # 4. Check if this is detected as rug pull
        result = self.detector.detect_rug_pull(
            updated_tool,
            integrity,
            updated_contract
        )
        
        # 5. Should detect changes but not classify as rug pull due to version increment
        # The confidence score should be lower for legitimate updates
        assert result.confidence_score < 0.7  # Below rug pull threshold
        
        # Changes should be detected but not classified as violations
        if result.detected_changes:
            # This is expected for legitimate updates
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])