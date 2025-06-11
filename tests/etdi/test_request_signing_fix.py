"""
Test for the fixed ETDI request signing implementation
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from mcp.etdi.types_extensions import create_signed_call_tool_request, ETDICallToolRequestParams
from mcp.etdi.crypto.request_signer import RequestSigner
from mcp.etdi.crypto.key_manager import KeyManager


class TestRequestSigningFix:
    """Test the fixed request signing implementation"""
    
    def test_etdi_call_tool_request_params(self):
        """Test ETDI enhanced CallToolRequestParams"""
        params = ETDICallToolRequestParams(
            name="test_tool",
            arguments={"param": "value"}
        )
        
        # Test adding signature headers
        signature_headers = {
            "X-ETDI-Signature": "test-signature",
            "X-ETDI-Timestamp": "1234567890",
            "X-ETDI-Key-ID": "test-key",
            "X-ETDI-Algorithm": "RS256"
        }
        
        params.add_signature_headers(signature_headers)
        
        # Verify headers were added
        assert params.etdi_signature == "test-signature"
        assert params.etdi_timestamp == "1234567890"
        assert params.etdi_key_id == "test-key"
        assert params.etdi_algorithm == "RS256"
        
        # Test getting signature headers
        retrieved_headers = params.get_signature_headers()
        assert retrieved_headers == signature_headers
        
        # Test has_signature
        assert params.has_signature() is True
    
    def test_create_signed_call_tool_request(self):
        """Test creating signed CallToolRequest"""
        signature_headers = {
            "X-ETDI-Signature": "test-signature",
            "X-ETDI-Timestamp": "1234567890"
        }
        
        request = create_signed_call_tool_request(
            name="test_tool",
            arguments={"param": "value"},
            signature_headers=signature_headers
        )
        
        # Verify request structure
        assert request.method == "tools/call"
        assert request.params.name == "test_tool"
        assert request.params.arguments == {"param": "value"}
        assert request.has_signature() is True
        
        # Verify signature headers
        retrieved_headers = request.get_signature_headers()
        assert retrieved_headers["X-ETDI-Signature"] == "test-signature"
        assert retrieved_headers["X-ETDI-Timestamp"] == "1234567890"
    
    @pytest.mark.asyncio
    async def test_request_signing_integration(self):
        """Test end-to-end request signing integration"""
        
        # Create a mock key manager and request signer
        key_manager = Mock(spec=KeyManager)
        mock_key_pair = Mock()
        key_manager.get_or_create_key_pair.return_value = mock_key_pair
        
        request_signer = Mock(spec=RequestSigner)
        request_signer.sign_tool_invocation.return_value = {
            "X-ETDI-Signature": "mock-signature",
            "X-ETDI-Timestamp": "1234567890",
            "X-ETDI-Key-ID": "mock-key-id",
            "X-ETDI-Algorithm": "RS256"
        }
        
        # Test signing a tool invocation
        tool_name = "test_tool"
        arguments = {"param": "value"}
        
        signature_headers = request_signer.sign_tool_invocation(tool_name, arguments)
        
        # Create signed request
        signed_request = create_signed_call_tool_request(
            name=tool_name,
            arguments=arguments,
            signature_headers=signature_headers
        )
        
        # Verify the request has all signature components
        assert signed_request.has_signature() is True
        assert signed_request.params.etdi_signature == "mock-signature"
        assert signed_request.params.etdi_timestamp == "1234567890"
        assert signed_request.params.etdi_key_id == "mock-key-id"
        assert signed_request.params.etdi_algorithm == "RS256"
        
        # Verify the request can be serialized (important for MCP transport)
        request_dict = signed_request.model_dump()
        assert "params" in request_dict
        assert "etdi_signature" in request_dict["params"]
        assert request_dict["params"]["etdi_signature"] == "mock-signature"
    
    def test_backward_compatibility(self):
        """Test that unsigned requests still work"""
        # Create standard request without signature
        params = ETDICallToolRequestParams(
            name="test_tool",
            arguments={"param": "value"}
        )
        
        # Should not have signature
        assert params.has_signature() is False
        assert params.get_signature_headers() == {}
        
        # Should still work as normal MCP request
        assert params.name == "test_tool"
        assert params.arguments == {"param": "value"}
    
    def test_partial_signature_headers(self):
        """Test handling of partial signature headers"""
        params = ETDICallToolRequestParams(
            name="test_tool",
            arguments={"param": "value"}
        )
        
        # Add only some signature headers
        partial_headers = {
            "X-ETDI-Signature": "test-signature"
            # Missing timestamp, key_id, algorithm
        }
        
        params.add_signature_headers(partial_headers)
        
        # Should have signature but only the provided headers
        assert params.has_signature() is True
        assert params.etdi_signature == "test-signature"
        assert params.etdi_timestamp is None
        assert params.etdi_key_id is None
        assert params.etdi_algorithm is None
        
        # get_signature_headers should only return non-None headers
        retrieved = params.get_signature_headers()
        assert retrieved == {"X-ETDI-Signature": "test-signature"}


if __name__ == "__main__":
    pytest.main([__file__])