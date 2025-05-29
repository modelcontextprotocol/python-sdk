"""
Tests for ETDI request signing functionality
"""

import pytest
import tempfile
import os
from datetime import datetime

from mcp.etdi.crypto import KeyManager, RequestSigner, SignatureVerifier
from mcp.etdi.types import ETDIToolDefinition, Permission, SecurityLevel


class TestKeyManager:
    """Test key management functionality"""
    
    def test_key_generation(self):
        """Test RSA key pair generation"""
        with tempfile.TemporaryDirectory() as temp_dir:
            key_manager = KeyManager(temp_dir)
            
            # Generate key pair
            key_pair = key_manager.generate_key_pair("test-key")
            
            assert key_pair.key_id == "test-key"
            assert key_pair.private_key is not None
            assert key_pair.public_key is not None
            assert key_pair.created_at is not None
            
            # Test fingerprint generation
            fingerprint = key_pair.public_key_fingerprint()
            assert len(fingerprint) == 16
    
    def test_key_persistence(self):
        """Test key storage and loading"""
        with tempfile.TemporaryDirectory() as temp_dir:
            key_manager = KeyManager(temp_dir)
            
            # Generate and save key
            original_key = key_manager.generate_key_pair("persistent-key")
            original_fingerprint = original_key.public_key_fingerprint()
            
            # Create new manager and load key
            new_manager = KeyManager(temp_dir)
            loaded_key = new_manager.load_key_pair("persistent-key")
            
            assert loaded_key is not None
            assert loaded_key.key_id == "persistent-key"
            assert loaded_key.public_key_fingerprint() == original_fingerprint


class TestRequestSigning:
    """Test request signing and verification"""
    
    def test_request_signing(self):
        """Test HTTP request signing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            key_manager = KeyManager(temp_dir)
            signer = RequestSigner(key_manager, "test-signer")
            
            # Sign a request
            method = "POST"
            url = "https://api.example.com/mcp/tools/call"
            headers = {"Content-Type": "application/json"}
            body = '{"tool_id": "test", "params": {}}'
            
            signature_headers = signer.sign_request(method, url, headers, body)
            
            # Verify signature headers are present
            assert "X-ETDI-Signature" in signature_headers
            assert "X-ETDI-Key-ID" in signature_headers
            assert "X-ETDI-Timestamp" in signature_headers
            assert "X-ETDI-Algorithm" in signature_headers
            
            assert signature_headers["X-ETDI-Algorithm"] == "RS256"
            assert signature_headers["X-ETDI-Key-ID"] == "test-signer"
    
    def test_signature_verification(self):
        """Test request signature verification"""
        with tempfile.TemporaryDirectory() as temp_dir:
            key_manager = KeyManager(temp_dir)
            signer = RequestSigner(key_manager, "test-verifier")
            verifier = SignatureVerifier(key_manager)
            
            # Sign a request
            method = "POST"
            url = "https://api.example.com/mcp/tools/call"
            headers = {"Content-Type": "application/json"}
            body = '{"tool_id": "calculator", "params": {"a": 5, "b": 3}}'
            
            signature_headers = signer.sign_request(method, url, headers, body)
            all_headers = {**headers, **signature_headers}
            
            # Verify the signature
            is_valid, error = verifier.verify_request_signature(method, url, all_headers, body)
            
            assert is_valid is True
            assert error is None
    
    def test_tool_invocation_signing(self):
        """Test tool invocation signing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            key_manager = KeyManager(temp_dir)
            signer = RequestSigner(key_manager, "tool-signer")
            verifier = SignatureVerifier(key_manager)
            
            # Sign tool invocation
            tool_id = "secure_calculator"
            parameters = {"operation": "add", "a": 10, "b": 20}
            
            signature_headers = signer.sign_tool_invocation(tool_id, parameters)
            
            # Verify tool invocation signature
            is_valid, error = verifier.verify_tool_invocation_signature(
                tool_id, parameters, signature_headers
            )
            
            assert is_valid is True
            assert error is None


class TestETDIToolDefinition:
    """Test ETDI tool definition with request signing"""
    
    def test_tool_definition_with_request_signing(self):
        """Test tool definition serialization with request signing field"""
        tool = ETDIToolDefinition(
            id="secure_tool",
            name="Secure Tool",
            version="1.0.0",
            description="A tool requiring request signing",
            provider={"id": "test-provider", "name": "Test Provider"},
            schema={"type": "object"},
            permissions=[
                Permission(
                    name="execute",
                    description="Execute the tool",
                    scope="tool:execute",
                    required=True
                )
            ],
            require_request_signing=True
        )
        
        # Test serialization
        tool_dict = tool.to_dict()
        assert tool_dict["require_request_signing"] is True
        
        # Test deserialization
        restored_tool = ETDIToolDefinition.from_dict(tool_dict)
        assert restored_tool.require_request_signing is True
        assert restored_tool.id == "secure_tool"
    
    def test_backward_compatibility(self):
        """Test backward compatibility with tools without request signing"""
        tool_dict = {
            "id": "legacy_tool",
            "name": "Legacy Tool",
            "version": "1.0.0",
            "description": "A legacy tool",
            "provider": {"id": "legacy", "name": "Legacy"},
            "schema": {"type": "object"},
            "permissions": [],
            "verification_status": "unverified"
            # Note: no require_request_signing field
        }
        
        # Should default to False
        tool = ETDIToolDefinition.from_dict(tool_dict)
        assert tool.require_request_signing is False


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests for request signing"""
    
    async def test_fastmcp_integration(self):
        """Test FastMCP integration with request signing"""
        # This would test the actual FastMCP integration
        # For now, just verify the types work correctly
        
        tool = ETDIToolDefinition(
            id="integration_tool",
            name="Integration Tool", 
            version="1.0.0",
            description="Integration test tool",
            provider={"id": "test", "name": "Test"},
            schema={"type": "object"},
            require_request_signing=True
        )
        
        assert tool.require_request_signing is True
        
        # Verify serialization round-trip
        serialized = tool.to_dict()
        deserialized = ETDIToolDefinition.from_dict(serialized)
        assert deserialized.require_request_signing is True


if __name__ == "__main__":
    pytest.main([__file__])